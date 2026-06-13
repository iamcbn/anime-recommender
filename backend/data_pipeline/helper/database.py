from psycopg2 import connect, extras, errors
from typing import List
import pandas as pd, numpy as np
from contextlib import contextmanager
import json



class DatabaseManager:

    def __init__(self, PARAMS: dict):
        self.PARAMS = PARAMS
        

    # ----------------------
    # CONNECTION HANDLERS
    # ----------------------

    @contextmanager
    def get_cursor(self):
        conn = connect(**self.PARAMS, cursor_factory=extras.DictCursor)
        try:
            with conn:
                with conn.cursor() as cur:
                    yield cur
        finally:
            conn.close()

    # ----------------------
    # DB STATE HANDLERS
    # ----------------------

    def get_db_state(self):
        # Establish connection       
        with self.get_cursor() as cur:
            # Ensure table exists (includes kaggle_version for new deployments)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS db_state (
                id SERIAL PRIMARY KEY,
                dataset_ref TEXT NOT NULL,
                dataset_version INT NOT NULL,
                kaggle_version BIGINT,
                applied_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)

            # One-off migration: add kaggle_version to existing tables that lack it
            cur.execute("""
            ALTER TABLE db_state ADD COLUMN IF NOT EXISTS kaggle_version BIGINT;
            """)
        

            cur.execute("SELECT * FROM db_state ORDER BY id DESC LIMIT 1")
            db_state = cur.fetchone()
        
        # Return dataset version and kaggle version
        if db_state is None:
            return None
        else:
            return {
                'dataset_version': db_state['dataset_version'],
                'kaggle_version': db_state['kaggle_version']
            }
        

    def update_db_state(self, dataset_ref: str, dataset_version: int, kaggle_version: int):
        # Establish connection
        with self.get_cursor() as cur:
            # Insert new state
            cur.execute("""
            INSERT INTO db_state (dataset_ref, dataset_version, kaggle_version)
            VALUES (%s, %s, %s)
            """, (dataset_ref, dataset_version, kaggle_version))



    # ----------------------
    # TABLE HANDLERS
    # ----------------------
        
    def truncate_table(self, table_name: str | List[str]):
        tables = table_name if isinstance(table_name, list) else [table_name]

        with self.get_cursor() as cur:
            for tbl in tables:
                cur.execute(f"TRUNCATE TABLE {tbl}")
    

    def insert_data(self, table_name: str, table_data: pd.DataFrame):

        df = table_data.copy()
        df = df.where(pd.notna(df), None)

        df = df.map(self._adapt_value)

        columns = ', '.join(df.columns)
        values = ', '.join(['%s'] * len(df.columns))
        query = f"INSERT INTO {table_name} ({columns}) VALUES ({values})"

        with self.get_cursor() as cur:
            extras.execute_batch(cur, query, df.values.tolist())
            print(f"Table {table_name} updated successfully.")




    def create_table(self, create_query: str):
        with self.get_cursor() as cur:
            cur.execute(create_query)
        
    
    def create_vector_extension(self):
        with self.get_cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")


    def create_vector_indexes(self):
        """
        Build HNSW indexes on the anime_embedding table for fast
        approximate nearest-neighbour search. Should be called AFTER
        data has been fully inserted/promoted into the main table.
        """
        with self.get_cursor() as cur:
            # Give PostgreSQL extra memory for the heavy index build
            cur.execute("SET maintenance_work_mem = '1GB';")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS anime_sbert_hnsw_idx
                ON anime_embedding USING hnsw (sbert_embedding vector_cosine_ops);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS anime_fasttext_hnsw_idx
                ON anime_embedding USING hnsw (fasttext_embedding vector_cosine_ops);
            """)
        print("HNSW vector indexes created successfully.")


    def drop_vector_indexes(self):
        """
        Drop HNSW indexes before bulk data promotion so that
        INSERT ... SELECT doesn't have to update the index row-by-row.
        """
        with self.get_cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS anime_sbert_hnsw_idx;")
            cur.execute("DROP INDEX IF EXISTS anime_fasttext_hnsw_idx;")
        print("HNSW vector indexes dropped.")


    def _adapt_value_old(self, x):
        if x is None:
            return None

        # pandas missing values
        if isinstance(x, float) and pd.isna(x):
            return None
        if x is pd.NA:
            return None

        # JSONB columns
        if isinstance(x, (list, dict)):
            return json.dumps(x)

        # pgvector (numpy arrays)
        if isinstance(x, np.ndarray):
            return x.tolist()

        return x
    

    def _adapt_value(self, x):
        # 1. Check for None (Python Null)
        if x is None:
            return None

        # 2. Check for Numpy Arrays (Embeddings) FIRST
        # We must do this before pd.isna(), otherwise pd.isna(array) causes the crash
        if isinstance(x, np.ndarray):
            return x.tolist()

        # 3. Check for Lists/Dicts (JSON columns)
        if isinstance(x, (list, dict)):
            return json.dumps(x)

        # 4. NOW it is safe to check for Scalar NaNs
        # (Floats, pd.NA, etc) without crashing on arrays
        if isinstance(x, float) and np.isnan(x):
            return None
            
        if pd.isna(x):
            return None

        return x
    
    
    def insert_temp_data(self, table_name: str, table_data: pd.DataFrame):
        """
        This function inserts data into the temp tables
        
        :param self: Description
        :param table_name: Description
        :type table_name: str
        :param table_data: Description
        :type table_data: pd.DataFrame
        """
        df = table_data.copy()
        df = df.where(pd.notna(df), None)
        df = df.map(self._adapt_value)

        columns = ', '.join(df.columns)
        values_placeholder = ', '.join(['%s'] * len(df.columns))
        query = f"INSERT INTO t{table_name} ({columns}) VALUES ({values_placeholder})"

        with self.get_cursor() as cur:
            try:
                # Try the fast batch method first
                extras.execute_batch(cur, query, df.values.tolist())
                print(f"Temp table t{table_name} updated successfully.")
            except (errors.NumericValueOutOfRange, errors.DataError) as e:
                # If batch fails, switch to slow debugging mode
                print(f"!!! Error detected in {table_name}. Switching to row-by-row debugging...")
                cur.connection.rollback() # Rollback the failed batch
                
                for index, row in df.iterrows():
                    try:
                        cur.execute(query, row.values.tolist())
                    except (errors.NumericValueOutOfRange, errors.DataError) as inner_e:
                        print(f"--- FAILURE FOUND ---")
                        print(f"Row Index: {index}")
                        print(f"Error Message: {inner_e}")
                        
                        # Check each value in the row to see which one is huge
                        for col, val in zip(df.columns, row.values):
                            print(f"{col}: {val} (Type: {type(val)})")
                        
                        raise inner_e # Stop completely to see the log
                    
    
    def promote_temp(self, table_name: str, table_data: pd.DataFrame):

        df = table_data.copy()

        columns = ', '.join(df.columns)
        query = f"INSERT INTO {table_name} ({columns}) SELECT {columns} FROM t{table_name}"

        with self.get_cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {table_name} CASCADE")
            cur.execute(query)

    def cleanup_temp(self, table_names: List):
        with self.get_cursor() as cur:
            for table_name in table_names:
                cur.execute(f"DROP TABLE IF EXISTS t{table_name} CASCADE")
        




DB_QUERIES = {
    'anime_core': """
        CREATE TABLE IF NOT EXISTS anime_core (
        id BIGINT PRIMARY KEY,
        idMal NUMERIC,
        siteUrl TEXT,
        title_english TEXT,
        title_romaji TEXT,
        title_native TEXT,
        title_userPreferred TEXT,
        synonyms JSONB,
        coverImage_large TEXT,
        coverImage_medium TEXT,
        bannerImage TEXT
        )""",

    "anime_content": """
        CREATE TABLE IF NOT EXISTS anime_content (
        id BIGINT PRIMARY KEY REFERENCES anime_core(id) ON DELETE CASCADE,

        description TEXT,
        genres JSONB,
        tags JSONB,

        format TEXT,
        source TEXT,
        countryOfOrigin TEXT,
        isAdult BOOLEAN,

        studios JSONB,

        relationship_type TEXT
    )""",
    
    "anime_temporal": """
        CREATE TABLE IF NOT EXISTS anime_temporal (
        id BIGINT PRIMARY KEY REFERENCES anime_core(id) ON DELETE CASCADE,
        season TEXT,
        seasonYear NUMERIC,
        episodes NUMERIC,
        duration NUMERIC,
        status TEXT,
        startDate_year INTEGER,
        endDate_year NUMERIC
        )""",

    "anime_metrics": """
        CREATE TABLE IF NOT EXISTS anime_metrics (
        id BIGINT PRIMARY KEY REFERENCES anime_core(id) ON DELETE CASCADE,

        averageScore NUMERIC,
        meanScore NUMERIC,

        popularity INTEGER,
        favourites INTEGER,
        trending INTEGER,

        rankings JSONB,
        recommendations JSONB     
        )""",

    "anime_embedding": """
        CREATE TABLE IF NOT EXISTS anime_embedding (
            id BIGINT PRIMARY KEY REFERENCES anime_core(id) ON DELETE CASCADE,
            embedding_text TEXT,
            sbert_embedding vector (384),
            fasttext_embedding  vector (300)
        )""",

}


TEMP_QUERIES = {
    'anime_core': """
        CREATE TABLE IF NOT EXISTS tanime_core (
        id BIGINT,
        idMal NUMERIC,
        siteUrl TEXT,
        title_english TEXT,
        title_romaji TEXT,
        title_native TEXT,
        title_userPreferred TEXT,
        synonyms JSONB,
        coverImage_large TEXT,
        coverImage_medium TEXT,
        bannerImage TEXT
        )""",

    "anime_content": """
        CREATE TABLE IF NOT EXISTS tanime_content (
        id BIGINT,

        description TEXT,
        genres JSONB,
        tags JSONB,

        format TEXT,
        source TEXT,
        countryOfOrigin TEXT,
        isAdult BOOLEAN,

        studios JSONB,

        relationship_type TEXT
    )""",
    
    "anime_temporal": """
        CREATE TABLE IF NOT EXISTS tanime_temporal (
        id BIGINT,
        season TEXT,
        seasonYear NUMERIC,
        episodes NUMERIC,
        duration NUMERIC,
        status TEXT,
        startDate_year INTEGER,
        endDate_year NUMERIC
        )""",

    "anime_metrics": """
        CREATE TABLE IF NOT EXISTS tanime_metrics (
        id BIGINT,

        averageScore NUMERIC,
        meanScore NUMERIC,

        popularity INTEGER,
        favourites INTEGER,
        trending INTEGER,

        rankings JSONB,
        recommendations JSONB     
        )""",

    "anime_embedding": """CREATE TABLE IF NOT EXISTS tanime_embedding (
            id BIGINT,
            embedding_text TEXT,
            sbert_embedding vector (384),
            fasttext_embedding  vector (300)
        )""",

}



  
