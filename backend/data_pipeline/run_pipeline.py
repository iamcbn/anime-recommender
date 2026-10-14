import kaggle
from .helper.fetch_data import KaggleDataVersionManager
from .helper.preprocess import Preprocessor
from .helper.database import DatabaseManager, DB_QUERIES, TEMP_QUERIES
from .helper.embedding import Embedder
from datetime import datetime
import time
from .config import config
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from requests.exceptions import SSLError
from pathlib import Path


import argparse

# ----------------------
# CLI ARGUMENTS
# ----------------------
parser = argparse.ArgumentParser(description="Run the anime data pipeline.")
parser.add_argument("--force", action="store_true", help="Force rebuild even if Kaggle dataset is up to date.")
args = parser.parse_args()

start_time = datetime.now()
start_timet = time.perf_counter()
KAGGLE_DATASET = "calebmwelsh/anilist-anime-dataset"


# ----------------------
# DATA FETCHING
# ----------------------

# Getting data directory
current_dir = Path(__file__).parent.resolve()
DATA_DIR = current_dir / "artefacts"


# Authenticate Kaggle API
kaggle.api.authenticate()

# Initialise DB connection early so we can read kaggle_version for the staleness check
PARAMS = config()
db_manager = DatabaseManager(PARAMS=PARAMS)
db_state = db_manager.get_db_state()

# Unpack the persisted state (None on very first run)
if db_state is not None:
    db_state_version = db_state['dataset_version']
    db_kaggle_version = db_state['kaggle_version']   # NULL for legacy rows
else:
    db_state_version = None
    db_kaggle_version = None

mgr = KaggleDataVersionManager(
    data_dir=DATA_DIR,
    dataset_ref=KAGGLE_DATASET
)

path, created, remote_version = mgr.check_and_prepare(db_kaggle_version=db_kaggle_version, db_state_version=db_state_version)

if not created and not args.force:
    print("Dataset already up to date (use --force to rebuild anyway)")
    print(f'Last run was at {datetime.now()}')
    exit(0)

if not created and args.force:
    print("Dataset is up to date, but --force was passed. Rebuilding from existing artefact...")
    # Re-use the existing path since a new one wasn't created
    if db_state_version is None:
        path = mgr.version_dir(1)
    else:
        path = mgr.version_dir(db_state_version)


print(f"New dataset version created at {path}")
# Now download dataset into path / "raw_data"
@retry(
    stop=stop_after_attempt(5), 
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type(SSLError))
def download_dataset():
    kaggle.api.dataset_download_file(
        dataset=KAGGLE_DATASET,
        path= (path/"raw_data"),
        file_name= 'anilist_anime_data_complete.xlsx'
        )
download_dataset()
print("Dataset download complete.")

# Derive STATE_VERSION from the actual directory that check_and_prepare created,
# ensuring the Preprocessor reads from exactly the same path the data was downloaded to.
STATE_VERSION = int(path.name.lstrip("v"))




# ----------------------
# DATA PREPROCESSING
# ----------------------

processor = Preprocessor(data_dir=DATA_DIR, state_version=STATE_VERSION)
tables = processor.preprocess()
print("Data preprocessing complete.")




# ----------------------
# DATA EMBEDDING
# ---------------------- 

EMBEDING_DF = tables["anime_embedding"].copy()

embedder = Embedder(EMBEDING_DF, retrain_fasttext=True)  

EMBEDING_DF = embedder.embed_dataframe('embedding_text')

tables["anime_embedding"] = EMBEDING_DF
print("Data embedding complete.")





# ----------------------
# DATA STORAGE
# ----------------------


db_manager.create_vector_extension()

if db_state_version is None:
    for table_name, query in DB_QUERIES.items():
        db_manager.create_table(create_query=query)
        print(f"{table_name} created successfully.")
        
    print("All tables created successfully.")

# Run schema migrations unconditionally — safe on both fresh and existing DBs.
# This is how new columns added to DB_QUERIES reach production without dropping tables.
db_manager.migrate_schema()

for table_name, query in TEMP_QUERIES.items():
    db_manager.create_table(create_query=query)
    print(f"Temp. table t{table_name} created successfully.")


insert_order = [
    "anime_core",
    "anime_content",
    "anime_temporal",
    "anime_metrics",
    "anime_embedding",
]


for table in insert_order:
    print(f"Inserting data into t{table} temp table")
    #print(check_overflow(tables[table], table))
    db_manager.insert_temp_data(table, tables[table])


# Drop HNSW indexes before bulk promotion to avoid slow row-by-row index updates
print("Dropping HNSW vector indexes before promotion")
db_manager.drop_vector_indexes()

# Pushing data from staging area to main DB
print(f"Pushing data from staging area to main DB")
for table in insert_order:
    db_manager.promote_temp(table, tables[table])


# Deleting temp tables
print("Deleting temp tables")
db_manager.cleanup_temp(insert_order)

# Rebuild HNSW indexes on the freshly populated table
print("Rebuilding HNSW vector indexes")
db_manager.create_vector_indexes()


db_manager.update_db_state(
    dataset_ref="calebmwelsh/anilist-anime-dataset",
    dataset_version=STATE_VERSION,
    kaggle_version=remote_version
)

print("Pipeline complete. State officially recorded.")
 
end_timet = time.perf_counter()
end_time = datetime.now()
time_diff = end_timet - start_timet
print(start_time, end_time, time_diff)
# C:/Dev/anime_recommender/anime/Scripts/Activate.ps1

  
# Don't forget to set retrain to true ----> ln 61: embedder = Embedder(EMBEDING_DF, retrain_fasttext=False)
