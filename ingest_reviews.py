# ==============================================================================
# SCRIPT: Daily Google Play Review Ingestion to Snowflake (FINAL WORKING VERSION)
# ==============================================================================

import pandas as pd
from google_play_scraper import reviews, Sort
import snowflake.connector
import os
from dotenv import load_dotenv

# --- 1. CONFIGURATION AND CREDENTIALS ---
load_dotenv()
SNOWFLAKE_USER = os.getenv("SNOWFLAKE_USER")
SNOWFLAKE_PASSWORD = os.getenv("SNOWFLAKE_PASSWORD")
SNOWFLAKE_ACCOUNT = os.getenv("SNOWFLAKE_ACCOUNT")
if not all([SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_ACCOUNT]):
    raise ValueError("Missing Snowflake credentials. Please check your .env file.")

SNOWFLAKE_WAREHOUSE = 'ANALYSIS_WH'
SNOWFLAKE_DATABASE = 'CHATGPT_REVIEWS_DB'
SNOWFLAKE_SCHEMA = 'PUBLIC'

# --- 2. DATA SCRAPING ---
APP_ID = 'com.openai.chatgpt'
REVIEWS_TO_SCRAPE = 1000

print(f"[PHASE 1/3] Scraping latest {REVIEWS_TO_SCRAPE} reviews...")
try:
    latest_reviews, _ = reviews(
        APP_ID, lang='en', country='us',
        sort=Sort.NEWEST, count=REVIEWS_TO_SCRAPE
    )
    if not latest_reviews:
        print("No new reviews found. Exiting.")
        exit()
    print(f"Successfully scraped {len(latest_reviews)} reviews.")
except Exception as e:
    print(f"An error occurred during scraping: {e}")
    exit()

# --- 3. DATA PREPARATION AND INGESTION ---
print("\n[PHASE 2/3] Connecting to Snowflake and preparing data...")
df = pd.DataFrame(latest_reviews)

df_to_load = df[['reviewId', 'userName', 'content', 'score', 'thumbsUpCount', 'at', 'appVersion']].copy()
df_to_load.rename(columns={
    'content': 'REVIEW_CONTENT', 'score': 'RATING',
    'thumbsUpCount': 'THUMBS_UP_COUNT', 'at': 'TIMESTAMP',
    'appVersion': 'APP_VERSION'
}, inplace=True)
df_to_load.columns = [col.upper() for col in df_to_load.columns]

parquet_file_path = 'reviews_data.parquet'
df_to_load.to_parquet(parquet_file_path, index=False)
print(f"Data saved to temporary file: {parquet_file_path}")

try:
    conn = snowflake.connector.connect(
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        account=SNOWFLAKE_ACCOUNT,
        warehouse=SNOWFLAKE_WAREHOUSE,
        database=SNOWFLAKE_DATABASE,
        schema=SNOWFLAKE_SCHEMA
    )
    print("Successfully connected to Snowflake.")
    cs = conn.cursor()

    cs.execute("CREATE OR REPLACE TEMP STAGE my_temp_stage;")
    print("Temporary stage created.")

    cs.execute("CREATE OR REPLACE FILE FORMAT my_parquet_format TYPE = 'PARQUET';")
    print("Parquet file format created.")

    file_uri = f"file://{os.path.abspath(parquet_file_path)}"
    print(f"Uploading file {file_uri} to stage...")
    cs.execute(f"PUT {file_uri} @my_temp_stage;")
    print("File uploaded successfully.")

    print("Copying data into a temporary staging table...")
    cs.execute("""
        CREATE OR REPLACE TEMP TABLE REVIEWS_STAGING
        USING TEMPLATE (
            SELECT ARRAY_AGG(OBJECT_CONSTRUCT(*))
            FROM TABLE(
                INFER_SCHEMA(
                    LOCATION=>'@my_temp_stage',
                    FILE_FORMAT=>'my_parquet_format'
                )
            )
        );
    """)
    cs.execute("COPY INTO REVIEWS_STAGING FROM @my_temp_stage FILE_FORMAT = 'my_parquet_format' MATCH_BY_COLUMN_NAME = 'CASE_INSENSITIVE';")
    print("Staging table loaded successfully.")

    merge_sql = """
    MERGE INTO REVIEWS T
    USING REVIEWS_STAGING S
    ON T.REVIEWID = S.REVIEWID
    WHEN NOT MATCHED THEN
        INSERT (REVIEWID, USERNAME, REVIEW_CONTENT, RATING, THUMBS_UP_COUNT, TIMESTAMP, APP_VERSION)
        VALUES (S.REVIEWID, S.USERNAME, S.REVIEW_CONTENT, S.RATING, S.THUMBS_UP_COUNT, TO_TIMESTAMP(S.TIMESTAMP / 1000000000), S.APP_VERSION);
    """

    print("Merging new data into final 'REVIEWS' table...")
    result = cs.execute(merge_sql)
    rows_inserted = result.fetchone()[0]
    print(f"Merge complete. {rows_inserted} new rows were added.")

except Exception as e:
    print(f"An error occurred during Snowflake ingestion: {e}")
finally:
    if 'cs' in locals():
        cs.close()
    if 'conn' in locals() and not conn.is_closed():
        conn.close()
        print("Snowflake connection closed.")

print("\n[PHASE 3/3] Ingestion process complete.")

if os.path.exists(parquet_file_path):
    os.remove(parquet_file_path)
    print(f"Temporary file {parquet_file_path} removed.")