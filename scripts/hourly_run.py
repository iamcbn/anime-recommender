"""
daily_run.py

Automated daily anime recommender test script.

Flow:
  1. Call the Gemini API to generate a creative, vague anime description,
     a difficulty score (1-10), and the ground-truth anime title.
  2. POST the description to the Modal FastAPI endpoint using the
     access_token header.
  3. If the response is 200 OK, append the full result as a single JSON
     line to anime_results.jsonl (JSON Lines format).

Environment variables required:
  GEMINI_API_KEY      — Google AI Studio API key
  MODAL_ACCESS_TOKEN  — FastAPI backend access token
"""

import json
import os
import sys
from datetime import datetime, timezone
import random

import requests
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODAL_API_URL = "https://iamcbn--anime-recommender-api-fastapi-app.modal.run/recommend"
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "..", "anime_results.jsonl")

GEMINI_MODEL = "gemini-3.6-flash"

# ---------------------------------------------------------------------------
# Gemini prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a creative anime quiz master. Your task is to write a unique, \
poetic quiz description every single day for an existing anime.

Rules:
- CRITICAL: The ground_truth MUST be a real, officially released anime series or movie. \
Do NOT invent a fictional anime title.
- The description must be VAGUE and poetic — do NOT name the anime directly.
- Vary the genre, tone, and style each time (shounen, slice-of-life, isekai, \
  psychological, mecha, romance, sports, horror, etc.).
- Vary the difficulty: sometimes be very obscure and cryptic, other times \
  slightly more descriptive.
- The ground_truth must be the exact, widely recognized title of the anime. \
Mix well-known hits with deeply obscure cult classics to keep it interesting.

"""

# Response structure
class AnimeQuizItem(BaseModel):
    genre: str = Field(description="The genre or vibe of the anime (e.g. shounen, isekai, psychological).")
    description: str = Field(description="A vague, creative anime description.")
    difficulty: int = Field(description="An integer between 1 and 10 — 1 is very easy, 10 is very hard.")
    ground_truth: str = Field(description="The exact anime title being secretly referred to.")

def generate_prompt_via_gemini(api_key: str) -> dict:
    """Use Gemini to generate a strongly-typed anime description and ground truth."""
    client = genai.Client(api_key=api_key)

    genres = [
    # Demographics
    "shounen",
    "shoujo",
    "seinen",
    "josei",
    "kodomomuke",
    
    # Core Narrative Genres
    "action",
    "adventure",
    "comedy",
    "drama",
    "fantasy",
    "horror",
    "mystery",
    "romance",
    "sci-fi",
    "slice of life",
    "sports",
    "supernatural",
    "suspense",
    "thriller",
    
    # Specialized Sub-Genres & Themes
    "isekai",
    "mecha",
    "mahou shoujo",
    "iyashikei",
    "cyberpunk",
    "steampunk",
    "gourmet",
    "idol",
    "psychological",
    "avant-garde",
    "surrealism",
    "historical",
    "mythology",
    "military",
    
    # Relationship & Tropes
    "harem",
    "reverse harem",
    "boys love",
    "girls love",
    "ecchi"
    ]
    selected_vibe = random.choice(genres)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=f"Generate today's anime description. Focus on a {selected_vibe} anime.",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=1024,
                    # Enforce the Pydantic schema natively
                    response_mime_type="application/json",
                    response_schema=AnimeQuizItem,
                ),
            )
            
            # Attempt to parse the response
            response_text = response.text.strip()
            quiz_json = json.loads(response_text)
            # Inject the locally-chosen genre before Pydantic validates
            quiz_json["genre"] = selected_vibe
            quiz_data = AnimeQuizItem(**quiz_json)

            return quiz_data.model_dump()
        
        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                print(f"  JSON parsing failed on attempt {attempt + 1}: {e}. Retrying...", file=sys.stderr)
                continue
            else:
                raise Exception(f"Gemini response parsing failed after {max_retries} attempts: {e}. Response was: {response.text[:200]}")
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  Generation failed on attempt {attempt + 1}: {e}. Retrying...", file=sys.stderr)
                continue
            else:
                raise



# ---------------------------------------------------------------------------
# Modal API call
# ---------------------------------------------------------------------------


def call_recommender_api(description: str, access_token: str) -> requests.Response:
    """POST the description to the Modal FastAPI endpoint."""
    headers = {
        "access_token": access_token,
        "Content-Type": "application/json",
    }
    payload = {"query": description}
    return requests.post(MODAL_API_URL, headers=headers, json=payload, timeout=60)


# ---------------------------------------------------------------------------
# Result persistence
# ---------------------------------------------------------------------------


def append_result(record: dict) -> None:
    """Append a single JSON record as a new line in anime_results.jsonl."""
    results_path = os.path.abspath(RESULTS_FILE)
    with open(results_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Result appended to: {results_path}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    # --- Load secrets from environment ---
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    modal_access_token = os.environ.get("MODAL_ACCESS_TOKEN")

    if not gemini_api_key:
        print("ERROR: GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    if not modal_access_token:
        print("ERROR: MODAL_ACCESS_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    NUM_RUNS = 2
    successful_runs = 0
    failed_runs = 0

    for i in range(NUM_RUNS):
        print(f"\n{'='*50}")
        print(f"Run {i + 1} of {NUM_RUNS}")
        print(f"{'='*50}")

        # --- Step 1: Generate prompt via Gemini ---
        print("Generating anime description via Gemini...")
        try:
            generated = generate_prompt_via_gemini(gemini_api_key)
        except Exception as exc:
            print(f"ERROR: Gemini generation failed — {exc}", file=sys.stderr)
            failed_runs += 1
            continue  # Skip to the next run instead of aborting all 4

        description = generated["description"]
        difficulty = generated["difficulty"]
        ground_truth = generated["ground_truth"]
        genre = generated["genre"]

        print(f"  Description : {description}")
        print(f"  Difficulty  : {difficulty}/10")
        print(f"  Ground truth: {ground_truth}")
        print(f"  Genre       : {genre}")

        # --- Step 2: Call the Modal recommender API ---
        print("\nSending request to Modal API...")
        try:
            response = call_recommender_api(description, modal_access_token)
        except requests.exceptions.RequestException as exc:
            print(f"ERROR: API request failed — {exc}", file=sys.stderr)
            failed_runs += 1
            continue  # Skip to the next run instead of aborting all 4

        print(f"  HTTP Status : {response.status_code}")

        # --- Step 3: Persist result if successful ---
        if response.status_code == 200:
            try:
                api_result = response.json()
            except json.JSONDecodeError:
                api_result = {"raw_response": response.text}

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "genre": genre,
                "description": description,
                "difficulty": difficulty,
                "ground_truth": ground_truth,
                "api_response": api_result,
                "status_code": response.status_code,
            }

            append_result(record)
            print(f"Run {i + 1} saved successfully.")
            successful_runs += 1
        else:
            print(
                f"WARNING: API returned non-200 status ({response.status_code}). "
                "Result NOT saved.",
                file=sys.stderr,
            )
            print(f"  Response body: {response.text[:500]}", file=sys.stderr)
            failed_runs += 1

    # --- Summary ---
    print(f"\n{'='*50}")
    print(f"Done. {successful_runs}/{NUM_RUNS} runs saved successfully.")
    if failed_runs > 0:
        print(f"WARNING: {failed_runs} run(s) failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
