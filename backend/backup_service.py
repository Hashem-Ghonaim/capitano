"""
Abo-Eyad ERP/CRM - Automated Backup Engine
==========================================
Features:
1. SQLAlchemy Reflection: Full schema reflection and data replication into an offline independent SQLite file (erp_crm.db).
2. Incremental Image Sync: Concurrent image downloading with ThreadPoolExecutor and local persistent cache.
3. Packaging & Manifest: Bundles SQLite DB + images + manifest.json into a dated ZIP archive (backup_YYYY-MM-DD_HH-MM-SS_full.zip).
4. Retention Policy: Automatically removes backups older than 30 days to optimize disk usage.
"""

import os
import sys
import json
import time
import shutil
import zipfile
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, MetaData, Table, Column, text

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("BackupService")


class BackupService:
    def __init__(self, database_url=None, base_dir=None):
        # Load environment variables if .env exists
        load_dotenv()

        if base_dir:
            self.base_dir = os.path.abspath(base_dir)
        else:
            self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

        self.backups_dir = os.path.join(self.base_dir, 'backups')
        self.cache_dir = os.path.join(self.backups_dir, 'cache')
        self.images_cache_dir = os.path.join(self.cache_dir, 'images')
        self.uploads_dir = os.path.join(self.base_dir, 'static', 'uploads')

        # Ensure directories exist
        os.makedirs(self.backups_dir, exist_ok=True)
        os.makedirs(self.images_cache_dir, exist_ok=True)

        # Database URL configuration
        raw_db_url = database_url or os.environ.get('DATABASE_URL')
        if not raw_db_url:
            sqlite_fallback = os.path.join(self.base_dir, 'erp_crm.db')
            logger.warning(f"No DATABASE_URL found. Using local SQLite database: {sqlite_fallback}")
            raw_db_url = f"sqlite:///{sqlite_fallback}"

        self.database_url = self._normalize_db_url(raw_db_url)
        self._init_cloudinary()

    def _normalize_db_url(self, url):
        """Normalize URL for SQLAlchemy dialect compatibility"""
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+pg8000://", 1)
        elif url.startswith("postgresql://") and "+pg8000" not in url and "+psycopg2" not in url:
            return url.replace("postgresql://", "postgresql+pg8000://", 1)
        return url

    def _init_cloudinary(self):
        """Initialize Cloudinary configuration if credentials exist"""
        try:
            import cloudinary
            import cloudinary.api
            from cloudinary.utils import cloudinary_url

            cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME', 'jjxkbp4v')
            api_key = os.environ.get('CLOUDINARY_API_KEY', '718338864994835')
            api_secret = os.environ.get('CLOUDINARY_API_SECRET', 'TDXOebqzLyjlf23JjlRGnTY3nCQ')

            cloudinary.config(
                cloud_name=cloud_name,
                api_key=api_key,
                api_secret=api_secret,
                secure=True
            )
            self.cloudinary_configured = True
            self.cloudinary_url_fn = cloudinary_url
            logger.info("Cloudinary client initialized.")
        except Exception as e:
            logger.warning(f"Cloudinary initialization skipped: {e}")
            self.cloudinary_configured = False
            self.cloudinary_url_fn = None

    def backup_database(self, sqlite_output_path):
        """
        Reflects all tables from the source database and copies full data
        into an independent SQLite database file.
        """
        logger.info(f"Connecting to source database: {self.database_url.split('@')[-1] if '@' in self.database_url else 'local'}")
        
        # Handle existing target sqlite file
        if os.path.exists(sqlite_output_path):
            try:
                os.remove(sqlite_output_path)
            except OSError:
                pass

        source_engine = create_engine(self.database_url)
        sqlite_engine = create_engine(f"sqlite:///{sqlite_output_path}")

        logger.info("Starting schema reflection from source database...")
        source_meta = MetaData()
        source_meta.reflect(bind=source_engine)
        logger.info(f"Reflected {len(source_meta.tables)} tables from source.")

        # Prepare SQLite metadata without strict foreign keys for easy offline dump
        sqlite_meta = MetaData()
        for table_name, src_table in source_meta.tables.items():
            cols = []
            for c in src_table.columns:
                cols.append(Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable))
            Table(table_name, sqlite_meta, *cols)

        try:
            # Create all tables in SQLite
            sqlite_meta.create_all(sqlite_engine)

            total_records = 0
            table_stats = {}

            # Transfer data table by table
            with source_engine.connect() as src_conn, sqlite_engine.connect() as sq_conn:
                # Optimize SQLite bulk writes
                sq_conn.execute(text("PRAGMA foreign_keys = OFF;"))
                sq_conn.execute(text("PRAGMA synchronous = OFF;"))
                sq_conn.execute(text("PRAGMA journal_mode = MEMORY;"))

                for table_name, src_table in source_meta.tables.items():
                    sq_table = sqlite_meta.tables[table_name]
                    
                    # Fetch records from source
                    result = src_conn.execute(src_table.select()).fetchall()
                    count = len(result)
                    table_stats[table_name] = count
                    total_records += count

                    if count > 0:
                        # Convert to list of dicts
                        # Insert in chunks of 5000 to maintain smooth memory profile
                        chunk_size = 5000
                        for i in range(0, count, chunk_size):
                            chunk = result[i:i + chunk_size]
                            rows = [dict(r._mapping) for r in chunk]
                            sq_conn.execute(sq_table.insert(), rows)
                        sq_conn.commit()

                    logger.debug(f"Table '{table_name}': {count} records copied.")

            db_file_size = os.path.getsize(sqlite_output_path)
            logger.info(f"Database backup complete: {total_records:,} records copied into SQLite ({db_file_size / (1024 * 1024):.2f} MB).")

            return {
                "total_records": total_records,
                "tables_count": len(table_stats),
                "table_stats": table_stats,
                "db_size_bytes": db_file_size
            }
        finally:
            sqlite_engine.dispose()
            source_engine.dispose()

    def get_referenced_images(self):
        """
        Scans database tables for referenced images.
        Inspects product_model, qassa, supplier_payment, pattern_tracking, etc.
        """
        source_engine = create_engine(self.database_url)
        referenced_images = set()

        # Target columns to inspect
        target_columns = [
            ("product_model", "image"),
            ("qassa", "custom_image"),
            ("supplier_payment", "receipt_image"),
            ("pattern_tracking", "image")
        ]

        with source_engine.connect() as conn:
            # Query target columns
            for table_name, col_name in target_columns:
                try:
                    query = text(f"SELECT DISTINCT {col_name} FROM {table_name} WHERE {col_name} IS NOT NULL")
                    rows = conn.execute(query).fetchall()
                    for (val,) in rows:
                        if val and isinstance(val, str):
                            cleaned = val.strip()
                            if cleaned and cleaned.lower() not in ('default.png', 'none', 'null'):
                                referenced_images.add(cleaned)
                except Exception as e:
                    logger.debug(f"Could not inspect {table_name}.{col_name}: {e}")

        logger.info(f"Found {len(referenced_images)} distinct referenced images in database.")
        return sorted(list(referenced_images))

    def _download_single_image(self, img_name):
        """
        Downloads or copies a single image into local cache.
        Returns: (img_name, success: bool, reason: str)
        """
        cache_path = os.path.join(self.images_cache_dir, img_name)
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
            return (img_name, True, "already_cached")

        # 1. Check local uploads folder first
        local_path = os.path.join(self.uploads_dir, img_name)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            try:
                shutil.copy2(local_path, cache_path)
                return (img_name, True, "copied_from_local")
            except Exception as e:
                logger.debug(f"Failed local copy for {img_name}: {e}")

        # 2. If it's a full HTTP/HTTPS URL
        if img_name.startswith("http://") or img_name.startswith("https://"):
            try:
                r = requests.get(img_name, timeout=12, stream=True)
                if r.status_code == 200:
                    with open(cache_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=16384):
                            f.write(chunk)
                    return (img_name, True, "downloaded_from_url")
            except Exception as e:
                return (img_name, False, f"url_error: {e}")

        # 3. Try Cloudinary
        if self.cloudinary_configured and self.cloudinary_url_fn:
            pid = img_name.rsplit('.', 1)[0] if '.' in img_name else img_name
            ext = img_name.rsplit('.', 1)[1] if '.' in img_name else None

            candidate_urls = []
            if ext:
                u1, _ = self.cloudinary_url_fn(pid, format=ext)
                candidate_urls.append(u1)
            u2, _ = self.cloudinary_url_fn(pid)
            candidate_urls.append(u2)
            if ext and ext.lower() == 'jpeg':
                u3, _ = self.cloudinary_url_fn(pid, format='jpg')
                candidate_urls.append(u3)

            for url in candidate_urls:
                try:
                    r = requests.get(url, timeout=12, stream=True)
                    if r.status_code == 200:
                        with open(cache_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=16384):
                                f.write(chunk)
                        return (img_name, True, "downloaded_from_cloudinary")
                except Exception:
                    continue

        return (img_name, False, "not_found")

    def sync_product_images(self, max_workers=8):
        """
        Synchronizes product images incrementally into the local cache using ThreadPoolExecutor.
        Skips files that already exist in the cache.
        """
        all_images = self.get_referenced_images()
        already_cached = []
        to_download = []

        for img in all_images:
            cache_path = os.path.join(self.images_cache_dir, img)
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
                already_cached.append(img)
            else:
                to_download.append(img)

        logger.info(f"Image sync status: {len(already_cached)} already in cache, {len(to_download)} need downloading.")

        downloaded_count = 0
        failed_count = 0
        failed_files = []

        if to_download:
            logger.info(f"Downloading {len(to_download)} missing images using {max_workers} worker threads...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_img = {executor.submit(self._download_single_image, img): img for img in to_download}
                for future in as_completed(future_to_img):
                    img = future_to_img[future]
                    try:
                        _, success, reason = future.result()
                        if success:
                            downloaded_count += 1
                        else:
                            failed_count += 1
                            failed_files.append((img, reason))
                    except Exception as e:
                        failed_count += 1
                        failed_files.append((img, str(e)))

        # Calculate cache size
        total_cache_bytes = 0
        cached_files_count = 0
        for f in os.listdir(self.images_cache_dir):
            fp = os.path.join(self.images_cache_dir, f)
            if os.path.isfile(fp):
                cached_files_count += 1
                total_cache_bytes += os.path.getsize(fp)

        logger.info(f"Image sync finished: {downloaded_count} newly downloaded, {failed_count} failed, {cached_files_count} total cached images ({total_cache_bytes / (1024 * 1024):.2f} MB).")

        return {
            "total_referenced": len(all_images),
            "already_cached": len(already_cached),
            "newly_downloaded": downloaded_count,
            "failed_downloads": failed_count,
            "failed_files": failed_files[:20],
            "total_cached_files": cached_files_count,
            "cache_size_bytes": total_cache_bytes
        }

    def cleanup_old_backups(self, days_to_keep=30):
        """
        Retention Policy: Removes backup zip files older than 30 days.
        """
        deleted_files = []
        now = datetime.now()
        cutoff_date = now - timedelta(days=days_to_keep)

        if not os.path.exists(self.backups_dir):
            return deleted_files

        for item in os.listdir(self.backups_dir):
            if item.startswith("backup_") and item.endswith("_full.zip"):
                file_path = os.path.join(self.backups_dir, item)
                if not os.path.isfile(file_path):
                    continue

                # Try parsing date from filename backup_YYYY-MM-DD_HH-MM-SS_full.zip
                file_time = None
                try:
                    parts = item.replace("backup_", "").replace("_full.zip", "").split("_")
                    date_part, time_part = parts[0], parts[1].replace("-", ":")
                    file_time = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
                except Exception:
                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))

                if file_time < cutoff_date:
                    try:
                        os.remove(file_path)
                        deleted_files.append(item)
                        logger.info(f"Retention policy: Deleted old backup '{item}' (Created: {file_time.strftime('%Y-%m-%d')}).")
                    except Exception as e:
                        logger.warning(f"Could not delete old backup {item}: {e}")

        return deleted_files

    def create_full_backup(self, max_image_workers=8, retention_days=30):
        """
        Main backup pipeline:
        1. Reflects and replicates DB to SQLite (erp_crm.db).
        2. Syncs referenced images into cache.
        3. Generates manifest.json report.
        4. Compresses DB + images + manifest into backup_YYYY-MM-DD_HH-MM-SS_full.zip.
        5. Executes 30-day retention cleanup.
        """
        start_time = time.time()
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_zip_filename = f"backup_{timestamp_str}_full.zip"
        backup_zip_path = os.path.join(self.backups_dir, backup_zip_filename)

        staging_dir = os.path.join(self.backups_dir, f"staging_{timestamp_str}")
        os.makedirs(staging_dir, exist_ok=True)

        logger.info(f"=== Starting Full Backup Process [{timestamp_str}] ===")

        try:
            # 1. Database backup to SQLite
            sqlite_file = os.path.join(staging_dir, "erp_crm.db")
            db_stats = self.backup_database(sqlite_file)

            # 2. Sync images
            image_stats = self.sync_product_images(max_workers=max_image_workers)

            # 3. Create Manifest
            manifest = {
                "backup_name": backup_zip_filename,
                "timestamp": datetime.now().isoformat(),
                "created_at_cairo": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "success",
                "database": {
                    "source_dialect": self.database_url.split("://")[0] if "://" in self.database_url else "unknown",
                    "file_name": "erp_crm.db",
                    "total_records": db_stats["total_records"],
                    "tables_count": db_stats["tables_count"],
                    "tables": db_stats["table_stats"],
                    "size_bytes": db_stats["db_size_bytes"]
                },
                "images": image_stats,
                "retention_policy": {
                    "days_to_keep": retention_days
                }
            }

            manifest_file = os.path.join(staging_dir, "manifest.json")
            with open(manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)

            # 4. Packaging into ZIP
            logger.info(f"Compressing package into {backup_zip_filename}...")
            with zipfile.ZipFile(backup_zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zip_out:
                # Add erp_crm.db
                zip_out.write(sqlite_file, arcname="erp_crm.db")
                # Add manifest.json
                zip_out.write(manifest_file, arcname="manifest.json")
                # Add cached images
                if os.path.exists(self.images_cache_dir):
                    for img_name in os.listdir(self.images_cache_dir):
                        img_path = os.path.join(self.images_cache_dir, img_name)
                        if os.path.isfile(img_path) and os.path.getsize(img_path) > 0:
                            zip_out.write(img_path, arcname=f"images/{img_name}")

            zip_size_bytes = os.path.getsize(backup_zip_path)
            zip_size_mb = zip_size_bytes / (1024 * 1024)

            # 5. Apply Retention Policy
            deleted_old_backups = self.cleanup_old_backups(days_to_keep=retention_days)

            elapsed_seconds = round(time.time() - start_time, 2)
            logger.info(f"=== Full Backup Successful! Size: {zip_size_mb:.2f} MB, Duration: {elapsed_seconds}s ===")

            return {
                "success": True,
                "zip_path": backup_zip_path,
                "zip_filename": backup_zip_filename,
                "zip_size_bytes": zip_size_bytes,
                "zip_size_mb": round(zip_size_mb, 2),
                "elapsed_seconds": elapsed_seconds,
                "manifest": manifest,
                "deleted_old_backups": deleted_old_backups
            }

        except Exception as e:
            logger.exception(f"Full backup failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "elapsed_seconds": round(time.time() - start_time, 2)
            }

        finally:
            # Clean up staging directory
            if os.path.exists(staging_dir):
                shutil.rmtree(staging_dir, ignore_errors=True)

