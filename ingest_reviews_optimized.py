# ==============================================================================
# OPTIMIZED SCRIPT: Google Play Review Ingestion to Snowflake
# ==============================================================================

import pandas as pd
import numpy as np
from google_play_scraper import reviews, Sort
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
import os
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from dotenv import load_dotenv
import sys
from contextlib import contextmanager

# --- 1. CONFIGURATION AND LOGGING SETUP ---
@dataclass
class Config:
    """Configuration class for the ingestion process."""
    # Snowflake Configuration
    snowflake_user: str
    snowflake_password: str
    snowflake_account: str
    snowflake_warehouse: str = 'ANALYSIS_WH'
    snowflake_database: str = 'CHATGPT_REVIEWS_DB'
    snowflake_schema: str = 'PUBLIC'
    
    # App Configuration
    app_id: str = 'com.openai.chatgpt'
    reviews_to_scrape: int = 1000
    batch_size: int = 500
    
    # Data Processing
    min_review_length: int = 10
    max_review_length: int = 5000

def setup_logging() -> logging.Logger:
    """Set up structured logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f'review_ingestion_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
        ]
    )
    return logging.getLogger(__name__)

def load_config() -> Config:
    """Load configuration from environment variables."""
    load_dotenv()
    
    required_vars = ['SNOWFLAKE_USER', 'SNOWFLAKE_PASSWORD', 'SNOWFLAKE_ACCOUNT']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    return Config(
        snowflake_user=os.getenv('SNOWFLAKE_USER'),
        snowflake_password=os.getenv('SNOWFLAKE_PASSWORD'),
        snowflake_account=os.getenv('SNOWFLAKE_ACCOUNT'),
        snowflake_warehouse=os.getenv('SNOWFLAKE_WAREHOUSE', 'ANALYSIS_WH'),
        snowflake_database=os.getenv('SNOWFLAKE_DATABASE', 'CHATGPT_REVIEWS_DB'),
        snowflake_schema=os.getenv('SNOWFLAKE_SCHEMA', 'PUBLIC'),
        app_id=os.getenv('APP_ID', 'com.openai.chatgpt'),
        reviews_to_scrape=int(os.getenv('REVIEWS_TO_SCRAPE', '1000')),
        batch_size=int(os.getenv('BATCH_SIZE', '500'))
    )

# --- 2. DATA VALIDATION AND PROCESSING ---
def validate_review_data(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and clean review data."""
    logger = logging.getLogger(__name__)
    
    initial_count = len(df)
    
    # Remove duplicates based on reviewId
    df = df.drop_duplicates(subset=['reviewId'], keep='first')
    
    # Filter out reviews that are too short (but be more lenient)
    df = df[df['content'].str.len() >= 5]  # Reduced from 10 to 5
    
    # Ensure required columns exist and have correct types
    required_columns = ['reviewId', 'userName', 'content', 'score', 'thumbsUpCount', 'at', 'appVersion']
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")
    
    # Type conversions with more lenient error handling
    df['score'] = pd.to_numeric(df['score'], errors='coerce')
    df['thumbsUpCount'] = pd.to_numeric(df['thumbsUpCount'], errors='coerce')
    df['at'] = pd.to_datetime(df['at'], errors='coerce')
    
    # Fill missing values instead of dropping rows
    df['userName'] = df['userName'].fillna('Anonymous')
    df['appVersion'] = df['appVersion'].fillna('Unknown')
    df['thumbsUpCount'] = df['thumbsUpCount'].fillna(0)
    
    # Only remove rows with critical missing data
    df = df.dropna(subset=['reviewId', 'content', 'score', 'at'])
    
    # Ensure score is within valid range
    df = df[(df['score'] >= 1) & (df['score'] <= 5)]
    
    final_count = len(df)
    logger.info(f"Data validation: {initial_count} -> {final_count} reviews ({initial_count - final_count} removed)")
    
    return df

def transform_data(df: pd.DataFrame) -> pd.DataFrame:
    """Transform data for Snowflake ingestion."""
    # Select and rename columns
    df_transformed = df[['reviewId', 'userName', 'content', 'score', 'thumbsUpCount', 'at', 'appVersion']].copy()
    
    # Rename columns to match Snowflake schema
    column_mapping = {
        'content': 'REVIEW_CONTENT',
        'score': 'RATING',
        'thumbsUpCount': 'THUMBS_UP_COUNT',
        'at': 'TIMESTAMP',
        'appVersion': 'APP_VERSION'
    }
    df_transformed = df_transformed.rename(columns=column_mapping)
    
    # Convert timestamp to proper format (remove timezone for Snowflake compatibility)
    df_transformed['TIMESTAMP'] = pd.to_datetime(df_transformed['TIMESTAMP']).dt.tz_localize(None)
    
    # Reset index to avoid pandas warnings
    df_transformed = df_transformed.reset_index(drop=True)
    
    return df_transformed

# --- 3. SNOWFLAKE OPERATIONS ---
@contextmanager
def snowflake_connection(config: Config):
    """Context manager for Snowflake connections."""
    conn = None
    try:
        conn = snowflake.connector.connect(
            user=config.snowflake_user,
            password=config.snowflake_password,
            account=config.snowflake_account,
            warehouse=config.snowflake_warehouse,
            database=config.snowflake_database,
            schema=config.snowflake_schema,
            autocommit=False
        )
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn and not conn.is_closed():
            conn.close()

def create_table_if_not_exists(conn: snowflake.connector.SnowflakeConnection, config: Config):
    """Create the reviews table if it doesn't exist."""
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {config.snowflake_database}.{config.snowflake_schema}.REVIEWS (
        REVIEWID VARCHAR(255) PRIMARY KEY,
        USERNAME VARCHAR(255),
        REVIEW_CONTENT TEXT,
        RATING INTEGER,
        THUMBS_UP_COUNT INTEGER,
        TIMESTAMP TIMESTAMP_NTZ,
        APP_VERSION VARCHAR(50)
    );
    """
    
    with conn.cursor() as cursor:
        cursor.execute(create_table_sql)

def ingest_data_optimized(conn: snowflake.connector.SnowflakeConnection, df: pd.DataFrame, config: Config) -> int:
    """Optimized data ingestion using write_pandas."""
    logger = logging.getLogger(__name__)
    
    try:
        # Use write_pandas for efficient bulk insert with proper parameters
        success, nchunks, nrows, _ = write_pandas(
            conn=conn,
            df=df,
            table_name='REVIEWS',
            database=config.snowflake_database,
            schema=config.snowflake_schema,
            chunk_size=config.batch_size,
            quote_identifiers=False,
            use_logical_type=True,  
            auto_create_table=False 
        )
        
        if success:
            logger.info(f"Successfully ingested {nrows} rows in {nchunks} chunks")
            return nrows
        else:
            raise Exception("Failed to write data to Snowflake")
            
    except Exception as e:
        logger.error(f"Error during data ingestion: {e}")
        raise

# --- 4. MAIN INGESTION PROCESS ---
def scrape_reviews(config: Config) -> pd.DataFrame:
    """Scrape reviews from Google Play Store."""
    logger = logging.getLogger(__name__)
    
    logger.info(f"Scraping {config.reviews_to_scrape} reviews for app {config.app_id}")
    
    try:
        reviews_data, continuation_token = reviews(
            config.app_id,
            lang='en',
            country='us',
            sort=Sort.NEWEST,
            count=config.reviews_to_scrape
        )
        
        if not reviews_data:
            logger.warning("No reviews found")
            return pd.DataFrame()
        
        df = pd.DataFrame(reviews_data)
        logger.info(f"Successfully scraped {len(df)} reviews")
        
        return df
        
    except Exception as e:
        logger.error(f"Error during scraping: {e}")
        raise

def main():
    """Main execution function."""
    logger = setup_logging()
    logger.info("Starting review ingestion process")
    
    try:
        # Load configuration
        config = load_config()
        logger.info(f"Configuration loaded: {config.app_id}, {config.reviews_to_scrape} reviews")
        
        # Scrape reviews
        df_raw = scrape_reviews(config)
        if df_raw.empty:
            logger.warning("No reviews to process")
            return
        
        # Validate and transform data
        df_validated = validate_review_data(df_raw)
        df_transformed = transform_data(df_validated)
        
        logger.info(f"Data prepared: {len(df_transformed)} reviews ready for ingestion")
        
        # Ingest to Snowflake
        with snowflake_connection(config) as conn:
            create_table_if_not_exists(conn, config)
            rows_inserted = ingest_data_optimized(conn, df_transformed, config)
            
        logger.info(f"Ingestion complete: {rows_inserted} rows inserted")
        
    except Exception as e:
        logger.error(f"Process failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
