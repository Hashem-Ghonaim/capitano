"""
Abo-Eyad ERP/CRM - Disaster Recovery Script (Restore from Backup)
================================================================
Restores database and product images from a full backup ZIP archive.

Usage:
  python restore_from_backup.py [path_to_backup_zip] [--target sqlite|postgres] [--yes]

Examples:
  python restore_from_backup.py                               # Restores latest backup to target DATABASE_URL
  python restore_from_backup.py backups/backup_2026-11-09.zip  # Restores specific archive
  python restore_from_backup.py --target sqlite --yes          # Restores latest backup directly to local erp_crm.db
"""

import os
import sys
import json
import zipfile
import tempfile
import argparse
import shutil
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine, MetaData, Table, text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("RestoreService")


def find_latest_backup(backups_dir):
    """Finds the most recent backup ZIP file in backups_dir"""
    if not os.path.exists(backups_dir):
        return None
    candidates = [
        f for f in os.listdir(backups_dir)
        if f.startswith("backup_") and f.endswith("_full.zip")
    ]
    if not candidates:
        candidates = [
            f for f in os.listdir(backups_dir)
            if f.startswith("backup_") and f.endswith(".zip")
        ]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return os.path.join(backups_dir, candidates[0])


def restore_backup(zip_path, target="postgres", auto_confirm=False):
    load_dotenv()
    base_dir = os.path.abspath(os.path.dirname(__file__))

    if not zip_path or not os.path.exists(zip_path):
        logger.error(f"Backup file not found: {zip_path}")
        return False

    logger.info(f"Inspecting backup archive: {zip_path}")

    # Inspect manifest inside ZIP
    manifest = None
    with zipfile.ZipFile(zip_path, 'r') as zf:
        namelist = zf.namelist()
        if "manifest.json" in namelist:
            with zf.open("manifest.json") as mf:
                manifest = json.load(mf)

    if manifest:
        db_info = manifest.get("database", {})
        img_info = manifest.get("images", {})
        print("\n" + "=" * 60)
        print("           BACKUP ARCHIVE SUMMARY           ")
        print("=" * 60)
        print(f"Archive:       {os.path.basename(zip_path)}")
        print(f"Created:       {manifest.get('created_at_cairo', manifest.get('timestamp'))}")
        print(f"Source:        {db_info.get('source_dialect', 'N/A')}")
        print(f"Total Tables:  {db_info.get('tables_count', 'N/A')}")
        print(f"Total Records: {db_info.get('total_records', 'N/A'):,}")
        print(f"Total Images:  {img_info.get('total_cached_files', img_info.get('total_in_backup', 'N/A'))}")
        print("=" * 60 + "\n")
    else:
        logger.warning("Manifest file not found inside archive. Proceeding with caution.")

    # Determine Target DB
    if target == "sqlite":
        target_db_url = f"sqlite:///{os.path.join(base_dir, 'erp_crm.db')}"
        target_name = "Local SQLite (erp_crm.db)"
    else:
        raw_url = os.environ.get("DATABASE_URL")
        if not raw_url:
            logger.error("DATABASE_URL environment variable is not set. Cannot restore to remote DB.")
            return False
        if raw_url.startswith("postgres://"):
            raw_url = raw_url.replace("postgres://", "postgresql+pg8000://", 1)
        elif raw_url.startswith("postgresql://") and "+pg8000" not in raw_url and "+psycopg2" not in raw_url:
            raw_url = raw_url.replace("postgresql://", "postgresql+pg8000://", 1)
        target_db_url = raw_url
        target_name = f"PostgreSQL ({raw_url.split('@')[-1] if '@' in raw_url else 'target'})"

    # Confirmation prompt
    print(f"⚠️  DANGER: You are about to restore this backup to:")
    print(f"👉 Target Database: {target_name}")
    print(f"👉 Target Images:   static/uploads/")
    print(f"This will OVERWRITE existing data in the target database!\n")

    if not auto_confirm:
        confirm = input("Type 'CONFIRM' or 'YES' to proceed: ").strip()
        if confirm.upper() not in ["CONFIRM", "YES"]:
            print("❌ Restoration aborted by user.")
            return False

    # Extract archive into a temporary folder
    temp_dir = tempfile.mkdtemp(prefix="restore_staging_")
    try:
        logger.info("Extracting backup archive...")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(temp_dir)

        sqlite_file = os.path.join(temp_dir, "erp_crm.db")
        if not os.path.exists(sqlite_file):
            logger.error("Archive does not contain erp_crm.db! Aborting.")
            return False

        # 1. Restore Database
        if target == "sqlite":
            dest_sqlite = os.path.join(base_dir, "erp_crm.db")
            logger.info(f"Copying extracted SQLite database to {dest_sqlite}...")
            shutil.copy2(sqlite_file, dest_sqlite)
            logger.info("✅ SQLite database replaced successfully.")
        else:
            logger.info(f"Migrating data from SQLite to {target_name}...")
            sq_engine = create_engine(f"sqlite:///{sqlite_file}")
            sq_meta = MetaData()
            sq_meta.reflect(bind=sq_engine)

            tgt_engine = create_engine(target_db_url)
            tgt_meta = MetaData()
            tgt_meta.reflect(bind=tgt_engine)

            is_postgres = "postgres" in target_db_url

            with tgt_engine.connect() as tgt_conn:
                if is_postgres:
                    tgt_conn.execute(text("SET session_replication_role = 'replica';"))

                for table_name in sq_meta.tables.keys():
                    if table_name not in tgt_meta.tables:
                        logger.warning(f"Table '{table_name}' does not exist in target database. Skipping.")
                        continue

                    tgt_table = tgt_meta.tables[table_name]
                    sq_table = sq_meta.tables[table_name]

                    # Read rows from SQLite
                    with sq_engine.connect() as sq_conn:
                        records = sq_conn.execute(sq_table.select()).fetchall()

                    # Truncate / delete existing records in target
                    tgt_conn.execute(tgt_table.delete())

                    if records:
                        valid_columns = set(c.name for c in tgt_table.columns)
                        rows_to_insert = [
                            {k: v for k, v in dict(r._mapping).items() if k in valid_columns}
                            for r in records
                        ]
                        # Insert in batches
                        batch_size = 5000
                        for i in range(0, len(rows_to_insert), batch_size):
                            batch = rows_to_insert[i:i + batch_size]
                            tgt_conn.execute(tgt_table.insert(), batch)
                        logger.info(f"Restored table '{table_name}': {len(records)} records.")
                    else:
                        logger.info(f"Table '{table_name}' is empty.")

                if is_postgres:
                    tgt_conn.execute(text("SET session_replication_role = 'origin';"))
                tgt_conn.commit()

            logger.info("✅ Remote database records restored successfully.")

        # 2. Restore Images to static/uploads
        images_dir = os.path.join(temp_dir, "images")
        uploads_dir = os.path.join(base_dir, "static", "uploads")
        os.makedirs(uploads_dir, exist_ok=True)

        if os.path.exists(images_dir):
            img_count = 0
            for img_file in os.listdir(images_dir):
                src = os.path.join(images_dir, img_file)
                dst = os.path.join(uploads_dir, img_file)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    img_count += 1
            logger.info(f"✅ Restored {img_count} product images into {uploads_dir}.")

        print("\n" + "🎉" * 20)
        print("   RESTORATION COMPLETED SUCCESSFULLY!   ")
        print("🎉" * 20 + "\n")
        return True

    except Exception as e:
        logger.exception(f"Restoration failed: {e}")
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Disaster recovery script for Abo-Eyad ERP")
    parser.add_argument("zip_path", nargs="?", default=None, help="Path to backup zip file (default: latest)")
    parser.add_argument("--target", choices=["postgres", "sqlite"], default="postgres", help="Target database")
    parser.add_argument("-y", "--yes", action="store_true", help="Auto confirm without prompt")
    args = parser.parse_args()

    zip_file = args.zip_path
    if not zip_file:
        backups_folder = os.path.join(os.path.abspath(os.path.dirname(__file__)), "backups")
        zip_file = find_latest_backup(backups_folder)
        if not zip_file:
            print("❌ No backup zip files found in 'backups/' directory.")
            sys.exit(1)

    success = restore_backup(zip_file, target=args.target, auto_confirm=args.yes)
    sys.exit(0 if success else 1)

