# ==============================================================================
# SCRIPT: BALANCED AND EFFICIENT REVIEW ANALYZER (CORRECTED GRAPH)
# DESCRIPTION: This script scrapes a substantial but manageable sample of
#              reviews (75,000). It performs the full comprehensive analysis,
#              with the "Review Volume" graph corrected to show daily data.
# ==============================================================================

# --- 1. SETUP AND IMPORTS ---
import pandas as pd
from google_play_scraper import reviews, Sort
import seaborn as sns
import matplotlib.pyplot as plt
import sys
from collections import Counter
from sklearn.feature_extraction.text import CountVectorizer
from wordcloud import STOPWORDS

# --- 2. CONFIGURATION ---
APP_ID = 'com.openai.chatgpt'
REVIEW_COUNT = 25000

print("--- Efficient Review Analysis (Corrected Graph) ---")
print(f"Target App: {APP_ID}")
print(f"Target Sample Size: {REVIEW_COUNT:,} reviews")
print("\n" + "="*60)
print(f"!! This scrape should take approximately 5-15 minutes. !!")
print("="*60 + "\n")


# --- 3. DATA ACQUISITION ---
print(f"[PHASE 1/6] ACQUIRING DATA ({REVIEW_COUNT:,} reviews)...")
try:
    result, _ = reviews(
        APP_ID, lang='en', country='us',
        sort=Sort.NEWEST, count=REVIEW_COUNT,
        filter_score_with=None
    )
    print(f"Successfully scraped {len(result)} recent reviews.")
except Exception as e:
    print(f"An error occurred during scraping: {e}", file=sys.stderr)
    sys.exit(1)

if not result:
    print("No reviews were scraped. Exiting.")
    sys.exit(1)


# --- 4. DATA COMPILATION AND PREPARATION ---
print("\n[PHASE 2/6] PREPARING DATAFRAME...")
df = pd.DataFrame(result)
df.rename(columns={'score': 'rating', 'at': 'timestamp', 'thumbsUpCount': 'thumbs_up_count', 'appVersion': 'app_version', 'content': 'review_content', 'replyContent': 'developer_reply'}, inplace=True)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.dropna(subset=['review_content'], inplace=True)
df['review_length'] = df['review_content'].apply(len)
print("Data preparation complete.")


# --- 5. DATA QUALITY SUMMARY TABLE ---
print("\n[PHASE 3/6] GENERATING DATA QUALITY REPORT...")
total_reviews = len(df)
missing_versions = df['app_version'].isnull().sum() if 'app_version' in df.columns else total_reviews
quality_stats = {
    'Metric': ['Total Reviews Scraped', 'Date Range Start', 'Date Range End', 'Missing App Versions', 'Median Review Length (chars)', 'Average Rating'],
    'Value': [f"{total_reviews:,}", df['timestamp'].min().strftime('%Y-%m-%d'), df['timestamp'].max().strftime('%Y-%m-%d'), f"{missing_versions:,} ({missing_versions/total_reviews:.2%})", f"{df['review_length'].median():.0f}", f"{df['rating'].mean():.2f}"]
}
quality_df = pd.DataFrame(quality_stats)
print("\n--- Data Quality and Completeness ---")
print(quality_df.to_string(index=False))


# --- 6. ADVANCED TEXT ANALYSIS PREPARATION ---
print("\n[PHASE 4/6] PREPARING TEXT FOR N-GRAM ANALYSIS...")
negative_reviews = df[df['rating'] <= 2]['review_content']
positive_reviews = df[df['rating'] >= 4]['review_content']
custom_stopwords = STOPWORDS.union(['app', 'chatgpt', 'chat', 'gpt', 'OpenAI', 'I', 'The', 'it', 's'])
def get_top_ngrams(corpus, n=2, top_k=15):
    try:
        vec = CountVectorizer(ngram_range=(n, n), stop_words=list(custom_stopwords)).fit(corpus)
        bag_of_words = vec.transform(corpus)
        sum_words = bag_of_words.sum(axis=0)
        words_freq = [(word, sum_words[0, idx]) for word, idx in vec.vocabulary_.items()]
        return sorted(words_freq, key = lambda x: x[1], reverse=True)[:top_k]
    except ValueError: return []
top_negative_bigrams = get_top_ngrams(negative_reviews)
top_positive_bigrams = get_top_ngrams(positive_reviews)


# --- 7. VISUALIZATION ---
print("\n[PHASE 5/6] GENERATING VISUALIZATIONS...")
sns.set_theme(style="whitegrid", palette="muted")
fig, axes = plt.subplots(3, 2, figsize=(18, 22))
fig.suptitle('Comprehensive Analysis of ChatGPT Google Play Reviews', fontsize=22, weight='bold')

# Plot 1: Ratings Distribution (No changes)
rating_counts = df['rating'].value_counts().sort_index()
sns.barplot(x=rating_counts.index, y=rating_counts.values, ax=axes[0, 0], palette="viridis")
axes[0, 0].set_title('1. Ratings Distribution', fontsize=16)

# ==============================================================================
# == FIX IMPLEMENTED HERE: Changed resampling from Weekly ('W') to Daily ('D') ==
reviews_per_day = df.set_index('timestamp').sort_index().resample('D').size()
sns.lineplot(data=reviews_per_day, ax=axes[0, 1], color='royalblue')
axes[0, 1].set_title('2. Review Volume Per Day (Recent History)', fontsize=16)
# ==============================================================================

# Plot 3: Review Length Distribution (No changes)
sns.histplot(df['review_length'], bins=50, kde=True, ax=axes[1, 0], color='darkorange')
axes[1, 0].set_title('3. Review Length Distribution (Characters)', fontsize=16)
axes[1, 0].set_xlim(0, 600)

# Plot 4: Average Rating by App Version (No changes)
if 'app_version' in df.columns and not df['app_version'].isnull().all():
    top_versions = df['app_version'].dropna().value_counts().nlargest(15).index
    df_top_versions = df[df['app_version'].isin(top_versions)]
    avg_rating_by_version = df_top_versions.groupby('app_version')['rating'].mean().sort_index()
    sns.barplot(x=avg_rating_by_version.values, y=avg_rating_by_version.index, ax=axes[1, 1], orient='h', palette="coolwarm_r")
    axes[1, 1].set_title('4. Avg Rating by App Version (Top 15)', fontsize=16)
else:
    axes[1, 1].text(0.5, 0.5, 'App Version Data Not Available', ha='center', va='center')
    axes[1, 1].set_title('4. Avg Rating by App Version', fontsize=16)

# Plot 5: Top Phrases in Negative Reviews (No changes)
if top_negative_bigrams:
    neg_bigrams_df = pd.DataFrame(top_negative_bigrams, columns=['bigram', 'count'])
    sns.barplot(x='count', y='bigram', data=neg_bigrams_df, ax=axes[2, 0], palette="Reds_r")
axes[2, 0].set_title('5. Top Phrases in Negative Reviews', fontsize=16)

# Plot 6: Top Phrases in Positive Reviews (No changes)
if top_positive_bigrams:
    pos_bigrams_df = pd.DataFrame(top_positive_bigrams, columns=['bigram', 'count'])
    sns.barplot(x='count', y='bigram', data=pos_bigrams_df, ax=axes[2, 1], palette="Greens_r")
axes[2, 1].set_title('6. Top Phrases in Positive Reviews', fontsize=16)

plt.tight_layout(rect=[0, 0.03, 1, 0.97])
plt.savefig('chatgpt_review_analysis_corrected.png', dpi=300)
print("\nVisualizations saved as 'chatgpt_review_analysis_corrected.png'")
plt.show()

# --- 8. FINAL SUMMARY ---
print("\n[PHASE 6/6] FINAL SUMMARY...")
print("Analysis complete.")