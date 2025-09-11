# ==============================================================================
# SCRIPT: FINAL, ROBUST Google Play Review Ingestion to Snowflake (DEFINITIVE VERSION)
# ==============================================================================

import pandas as pd
from google_play_scraper import reviews, Sort
import snowflake.connector
import os
from dotenv import load_dotenv
import logging
import sys

# --- 1. SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)
load_dotenv()

# --- 2. CONFIGURATION ---
SNOWFLAKE_USER = os.getenv("SNOWFLAKE_USER")
SNOWFLAKE_PASSWORD = os.getenv("SNOWFLAKE_PASSWORD")
SNOWFLAKE_ACCOUNT = os.getenv("SNOWFLAKE_ACCOUNT")
if not all([SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_ACCOUNT]):
    raise ValueError("Missing Snowflake credentials. Please check your .env file.")

SNOWFLAKE_WAREHOUSE = 'ANALYSIS_WH'
SNOWFLAKE_DATABASE = 'CHATGPT_REVIEWS_DB'
SNOWFLAKE_SCHEMA = 'PUBLIC'
APP_ID = 'com.openai.chatgpt'
REVIEWS_TO_SCRAPE = int(os.getenv('REVIEWS_TO_SCRAPE', '10000'))

# --- 3. MAIN EXECUTION ---
def main():
    logger.info("Starting review ingestion process.")

    # --- EXTRACT ---
    logger.info(f"Scraping latest {REVIEWS_TO_SCRAPE} reviews...")
    try:
        reviews_data, _ = reviews(APP_ID, lang='en', country='us', sort=Sort.NEWEST, count=REVIEWS_TO_SCRAPE)
        if not reviews_data:
            logger.warning("No new reviews found. Exiting.")
            return
        df_raw = pd.DataFrame(reviews_data)
        logger.info(f"Successfully scraped {len(df_raw)} raw reviews.")
    except Exception as e:
        logger.error(f"Failed during scraping: {e}", exc_info=True)
        sys.exit(1)

    # --- TRANSFORM AND VALIDATE ---
    initial_count = len(df_raw)
    if 'reviewCreatedVersion' in df_raw.columns:
        df_raw['appVersion'] = df_raw['reviewCreatedVersion']
    required_cols = ['reviewId', 'userName', 'content', 'score', 'thumbsUpCount', 'at', 'appVersion']
    for col in required_cols:
        if col not in df_raw.columns:
            df_raw[col] = None
    df_transformed = df_raw[required_cols].copy()
    df_transformed.dropna(subset=['reviewId', 'content', 'score', 'at'], inplace=True)
    df_transformed['score'] = pd.to_numeric(df_transformed['score'], errors='coerce').astype('Int64')
    df_transformed['thumbsUpCount'] = pd.to_numeric(df_transformed['thumbsUpCount'], errors='coerce').fillna(0).astype(int)
    # CRITICAL: Ensure 'at' is timezone-naive for correct conversion later
    df_transformed['at'] = pd.to_datetime(df_transformed['at'], errors='coerce').dt.tz_localize(None)
    df_transformed.rename(columns={
        'reviewId': 'REVIEWID', 'userName': 'USERNAME', 'content': 'REVIEW_CONTENT',
        'score': 'RATING', 'thumbsUpCount': 'THUMBS_UP_COUNT', 'at': 'TIMESTAMP',
        'appVersion': 'APP_VERSION'
    }, inplace=True)
    final_count = len(df_transformed)
    logger.info(f"Data validation complete. {final_count} of {initial_count} reviews are valid.")
    if final_count == 0:
        logger.warning("No valid reviews to load. Exiting.")
        return

    # --- LOAD ---
    parquet_file_path = 'reviews_data.parquet'
    df_transformed.to_parquet(parquet_file_path, index=False)
    logger.info(f"Data saved to temporary file: {parquet_file_path}")

    conn = None
    try:
        conn = snowflake.connector.connect(
            user=SNOWFLAKE_USER, password=SNOWFLAKE_PASSWORD, account=SNOWFLAKE_ACCOUNT,
            warehouse=SNOWFLAKE_WAREHOUSE, database=SNOWFLAKE_DATABASE, schema=SNOWFLAKE_SCHEMA
        )
        logger.info("Successfully connected to Snowflake.")
        cs = conn.cursor()
        
        cs.execute("CREATE OR REPLACE TEMP STAGE my_temp_stage FILE_FORMAT = (TYPE = 'PARQUET');")
        logger.info("Temporary stage and file format created.")
        
        file_uri = f"file://{os.path.abspath(parquet_file_path)}"
        logger.info(f"Uploading file {file_uri} to stage...")
        cs.execute(f"PUT {file_uri} @my_temp_stage;")
        logger.info("File uploaded successfully.")
        
        # ==============================================================================
        # == DEFINITIVE FIX IMPLEMENTED HERE: Use a temporary table for staging ==
        # Step 1: Create a temporary staging table by inferring schema from the file
        cs.execute("""
            CREATE OR REPLACE TEMP TABLE REVIEWS_STAGING AS
            SELECT
                $1:REVIEWID::VARCHAR AS REVIEWID,
                $1:USERNAME::VARCHAR AS USERNAME,
                $1:REVIEW_CONTENT::VARCHAR AS REVIEW_CONTENT,
                $1:RATING::INT AS RATING,
                $1:THUMBS_UP_COUNT::INT AS THUMBS_UP_COUNT,
                TO_TIMESTAMP_NTZ($1:TIMESTAMP::BIGINT, 9) AS TIMESTAMP,
                $1:APP_VERSION::VARCHAR AS APP_VERSION
            FROM @my_temp_stage;
        """)
        logger.info("Temporary staging table created and populated successfully.")

        # Step 2: Merge from the well-defined staging table into the final table
        merge_sql = """
        MERGE INTO REVIEWS T
        USING REVIEWS_STAGING S
        ON T.REVIEWID = S.REVIEWID
        WHEN NOT MATCHED THEN
            INSERT (REVIEWID, USERNAME, REVIEW_CONTENT, RATING, THUMBS_UP_COUNT, TIMESTAMP, APP_VERSION)
            VALUES (S.REVIEWID, S.USERNAME, S.REVIEW_CONTENT, S.RATING, S.THUMBS_UP_COUNT, S.TIMESTAMP, S.APP_VERSION);
        """
        # ==============================================================================
        
        logger.info("Merging new data into final 'REVIEWS' table...")
        result = cs.execute(merge_sql)
        rows_inserted = result.fetchone()[0]
        logger.info(f"Merge complete. {rows_inserted} new rows were added.")

    except Exception as e:
        logger.error(f"PROCESS FAILED: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if 'cs' in locals(): cs.close()
        if conn and not conn.is_closed(): conn.close()
        logger.info("Snowflake connection closed.")
        if os.path.exists(parquet_file_path):
            os.remove(parquet_file_path)
            logger.info(f"Temporary file {parquet_file_path} removed.")

if __name__ == "__main__":
    main()