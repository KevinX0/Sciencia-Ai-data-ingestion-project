# ==============================================================================
# SCRIPT: FINAL STRATEGIC BUSINESS INTELLIGENCE REPORT (DEFINITIVE VERSION)
# ==============================================================================

# --- 1. SETUP AND IMPORTS ---
import pandas as pd
import numpy as np
from google_play_scraper import reviews, Sort
import seaborn as sns
import matplotlib.pyplot as plt
import sys
import re
from collections import Counter
from sklearn.feature_extraction.text import CountVectorizer
from wordcloud import STOPWORDS
from scipy import stats

# --- 2. CONFIGURATION ---
APP_ID = 'com.openai.chatgpt'
REVIEW_COUNT = 25000

print("--- Sciencia AI: Final Strategic Business Intelligence Report ---")
print(f"Target App: {APP_ID}")
print(f"Sample Size: {REVIEW_COUNT:,} reviews")
print("-" * 60 + "\n")


# --- 3. DATA ACQUISITION AND PREPARATION ---
print(f"[PHASE 1/5] ACQUIRING AND PREPARING DATA...")
try:
    result, _ = reviews(APP_ID, lang='en', country='us', sort=Sort.NEWEST, count=REVIEW_COUNT)
    print(f"Successfully scraped {len(result)} reviews.")
except Exception as e:
    print(f"An error occurred: {e}", file=sys.stderr)
    sys.exit(1)

df = pd.DataFrame(result)
df.rename(columns={
    'score': 'rating', 'at': 'timestamp', 'thumbsUpCount': 'thumbs_up_count',
    'appVersion': 'app_version', 'content': 'review_content'
}, inplace=True)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.dropna(subset=['review_content'], inplace=True)
df['review_content_lower'] = df['review_content'].str.lower()
print("Data preparation complete.")


# --- 4. METADATA AND RAW DATA SAMPLES ---
print("\n[PHASE 2/5] GENERATING METADATA AND RAW DATA SAMPLES...")
metadata_dict = {
    'Field Name': ['reviewId', 'userName', 'review_content', 'rating', 'thumbs_up_count', 'timestamp', 'app_version'],
    'Data Type': ['Text', 'Text', 'Text', 'Integer', 'Integer', 'Datetime', 'Text'],
    'Description': [
        'Unique identifier for the review.', 'Public display name of the reviewer.',
        'The full text of the user\'s feedback.', 'The star rating given by the user (1-5).',
        'Number of users who found the review helpful.', 'The date and time the review was submitted.',
        'The app version the user had when reviewing.'
    ]
}
metadata_df = pd.DataFrame(metadata_dict)
print("\n--- Metadata Dictionary ---")
print(metadata_df.to_markdown(index=False))

print("\n--- Raw Data Sample (First 5 Rows) ---")
sample_columns = ['userName', 'rating', 'thumbs_up_count', 'timestamp', 'app_version', 'review_content']
display_cols = [col for col in sample_columns if col in df.columns]
sample_df = df[display_cols].head()
print(sample_df.to_markdown(index=False))


# --- 5. PERFORMING DEEP-DIVE ANALYSES ---
print("\n[PHASE 3/5] PERFORMING DEEP-DIVE ANALYSES...")
def get_top_ngrams(corpus, n=2, top_k=10):
    custom_stopwords = STOPWORDS.union(['app', 'chatgpt', 'chat', 'gpt', 'openai', 'i', 'the', 'it', 's'])
    try:
        vec = CountVectorizer(ngram_range=(n, n), stop_words=list(custom_stopwords)).fit(corpus)
        bag_of_words = vec.transform(corpus)
        sum_words = bag_of_words.sum(axis=0)
        words_freq = [(word, sum_words[0, idx]) for word, idx in vec.vocabulary_.items()]
        return sorted(words_freq, key = lambda x: x[1], reverse=True)[:top_k]
    except ValueError: return []

top_1_percent_helpful = df.nlargest(int(len(df) * 0.01), 'thumbs_up_count')
influential_negative = top_1_percent_helpful[top_1_percent_helpful['rating'] <= 2]
top_influential_neg_phrases = get_top_ngrams(influential_negative['review_content_lower'])

def get_top_unigrams(corpus, top_k=10):
    custom_stopwords = STOPWORDS.union(['app', 'chatgpt', 'chat', 'gpt', 'openai', 'i', 'the', 'it', 's', 'new', 'update', 'model'])
    try:
        vec = CountVectorizer(ngram_range=(1, 1), stop_words=list(custom_stopwords)).fit(corpus)
        bag_of_words = vec.transform(corpus)
        sum_words = bag_of_words.sum(axis=0)
        words_freq = [(word, sum_words[0, idx]) for word, idx in vec.vocabulary_.items()]
        return sorted(words_freq, key = lambda x: x[1], reverse=True)[:top_k]
    except ValueError: return []
update_reviews_df = influential_negative[influential_negative['review_content_lower'].str.contains('new update|new model', na=False)]
update_context_words = get_top_unigrams(update_reviews_df['review_content_lower'])

feature_keywords = {
    'Voice': ['voice', 'speak', 'talk', 'audio'], 'Image': ['image', 'picture', 'photo', 'dall-e', 'dalle'],
    'Model Performance': ['gpt-4o', 'gpt-5', 'new model', 'old version', 'smarter', 'dumber']
}
report_card = []
for feature, keywords in feature_keywords.items():
    feature_df = df[df['review_content_lower'].str.contains('|'.join(keywords), na=False)]
    if not feature_df.empty:
        avg_rating = feature_df['rating'].mean()
        top_phrase = get_top_ngrams(feature_df['review_content_lower'], top_k=1)
        report_card.append({'Feature': feature, 'Avg Rating': avg_rating, 'Top Mentioned Phrase': top_phrase[0][0] if top_phrase else "N/A"})
report_card_df = pd.DataFrame(report_card)

model_performance_keywords = feature_keywords['Model Performance']
model_performance_reviews_df = df[df['review_content_lower'].str.contains('|'.join(model_performance_keywords), na=False)]
other_reviews_df = df[~df.index.isin(model_performance_reviews_df.index)]
model_performance_ratings = model_performance_reviews_df['rating']
other_ratings = other_reviews_df['rating']
if len(model_performance_ratings) > 1 and len(other_ratings) > 1:
    t_stat, p_value = stats.ttest_ind(model_performance_ratings, other_ratings, equal_var=False)
else:
    p_value = 1.0

four_star_reviews = df[df['rating'] == 4]['review_content_lower']
four_star_phrases = get_top_ngrams(four_star_reviews)

problem_keywords = {
    'Bug Reports': ['crash', 'error', 'bug', 'doesn\'t work', 'broken'], 'Performance': ['slow', 'laggy', 'lag', 'latency', 'loading'],
    'Monetization': ['price', 'cost', 'subscription', 'free version', 'limit']
}
for category, keywords in problem_keywords.items():
    df[category] = df['review_content_lower'].str.contains('|'.join(keywords), na=False)
health_trends = df.set_index('timestamp').resample('D')[list(problem_keywords.keys())].sum()
daily_review_counts = df.set_index('timestamp').resample('D').size()
health_trends_percent = health_trends.div(daily_review_counts, axis=0) * 100


# --- 6. GENERATING VISUALS AND TEXT OUTPUTS ---
print("\n[PHASE 4/5] GENERATING VISUALS AND TEXT OUTPUTS...")
fig, axes = plt.subplots(2, 2, figsize=(18, 16))
fig.suptitle('Strategic Intelligence Dashboard for ChatGPT', fontsize=22, weight='bold')

# Plot 1: (CORRECTED) Top Influential Negative Feedback Themes
ax1 = axes[0, 0]
influential_neg_df = pd.DataFrame(top_influential_neg_phrases, columns=['phrase', 'count'])
sns.barplot(x='count', y='phrase', data=influential_neg_df, ax=ax1, color='#d62728')
ax1.set_title('1. Top Concerns of Most Influential Users (Top 1% Voted)', fontsize=16)
ax1.set_xlabel("Frequency in Influential Negative Reviews")

# Plot 2: Top "Almost Perfect" Feedback
ax2 = axes[0, 1]
four_star_df = pd.DataFrame(four_star_phrases, columns=['phrase', 'count'])
sns.barplot(x='count', y='phrase', data=four_star_df, ax=ax2, palette="YlOrBr_r")
ax2.set_title('2. Top Feedback from "Almost Perfect" 4-Star Reviews', fontsize=16)

# Plot 3: Feature Report Card
ax3 = axes[1, 0]
if not report_card_df.empty:
    sns.barplot(x='Avg Rating', y='Feature', data=report_card_df.sort_values('Avg Rating'), ax=ax3, palette="coolwarm")
    ax3.set_title('3. Feature-Specific "Report Card" (Average Rating)', fontsize=16)
    ax3.set_xlim(left=min(2.0, report_card_df['Avg Rating'].min() - 0.2))

# Plot 4: (CORRECTED) Product Health Dashboard
ax4 = axes[1, 1]
health_trends_percent.plot(kind='line', ax=ax4, marker='o', markersize=4)
ax4.set_title('4. Product Health Dashboard (% of Daily Reviews)', fontsize=16)
ax4.set_ylabel('% of Daily Reviews by Category')
ax4.legend(title='Complaint Category')

plt.tight_layout(rect=[0, 0.03, 1, 0.96])
plt.savefig('chatgpt_strategic_report_final.png', dpi=300)
print("\nStrategic dashboard saved as 'chatgpt_strategic_report_final.png'")
plt.show()

# --- 7. PRINTING TEXT OUTPUTS FOR REPORT ---
print("\n--- TEXT OUTPUTS FOR FINAL REPORT ---")
print(f"\nP-VALUE FOR T-TEST: {p_value:.10f}\n")
print("\n### Brief 1: The Community Voice ###")
print("**Top themes from the most influential NEGATIVE reviews:**")
print(pd.DataFrame(top_influential_neg_phrases, columns=['Phrase', 'Frequency']).to_markdown(index=False))

print("\n\n### Deep-Dive: What about the 'New Update' is problematic? ###")
print("**Top descriptive words from influential reviews complaining about the 'new update' or 'new model':**")
print(pd.DataFrame(update_context_words, columns=['Problem Keyword', 'Frequency']).to_markdown(index=False))

print("\n\n### Brief 2: Feature Report Card ###")
if not report_card_df.empty:
    report_card_df['Avg Rating'] = report_card_df['Avg Rating'].map('{:.2f}'.format)
print(report_card_df.to_markdown(index=False))

print("\n\n### Brief 3: The Conversion Opportunity ###")
print("**Top feedback themes from 4-star reviewers:**")
print(four_star_df.to_markdown(index=False))

# --- 8. FINAL SUMMARY ---
print("\n[PHASE 5/5] Analysis complete.")