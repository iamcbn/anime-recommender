# backend/rag_pipeline/config.py
import os
from dotenv import load_dotenv

load_dotenv()


def config() -> dict:
    """
    Returns PostgreSQL connection parameters.
    
    Supports Supabase PgBouncer transaction pooler (port 6543)
    as well as direct/local PostgreSQL (port 5432).
    """
    host = os.getenv("DB_HOST", "localhost")
    
    # Auto-detect Supabase pooler default port (6543) vs direct Postgres port (5432)
    default_port = 6543 if ("pooler" in host or "supabase.co" in host) else 5432
    raw_port = os.getenv("DB_PORT")
    port = int(raw_port) if raw_port and raw_port.isdigit() else default_port
    
    database = os.getenv("DB_NAME", "postgres")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")
    
    # Supabase strictly mandates SSL; local development can default to 'prefer'
    default_ssl = "require" if ("pooler" in host or "supabase.co" in host) else "prefer"
    sslmode = os.getenv("DB_SSLMODE", default_ssl)
    
    params = {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
    }
    
    if sslmode:
        params["sslmode"] = sslmode
        
    # Guard against indefinite TCP hangs during network partitions
    connect_timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
    params["connect_timeout"] = connect_timeout
    
    # Application name for PostgreSQL connection monitoring
    params["application_name"] = os.getenv("DB_APP_NAME", "anime_recommender_rag")
    
    return params


if __name__ == "__main__":
    import pprint
    cfg = config()
    safe_cfg = {k: (v if k != "password" else "********") for k, v in cfg.items()}
    pprint.pprint(safe_cfg)