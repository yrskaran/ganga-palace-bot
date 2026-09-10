# Models to fallback smoothly
MODELS_TO_TRY = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "qwen/qwen3.6-27b"
]

def get_ai_reply(user_message):
    system_prompt = f"""
Aap Hotel Ganga Palace Haridwar ke polite reception manager 'Aman' hain.
Aapka andaz bilkul natural, humble WhatsApp human typing jaisa hona chahiye.

Rules:
1. Har jawab 1 ya 2 short sentences me dein.
2. Hamesha 'Ji', 'Aap', aur respectful Hinglish use karein.
3. Extra technical ya formal words mat use karein.

HOTEL DATA:
{HOTEL_CONTEXT}
"""
    for model_name in MODELS_TO_TRY:
        try:
            completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model=model_name,
                temperature=0.3,
                max_tokens=250
            )
            raw_text = completion.choices[0].message.content
            reply = clean_reply(raw_text)
            if reply:
                print(f"--- SUCCESS WITH MODEL: {model_name} ---")
                return reply
        except Exception as e:
            print(f"--- FAILED ON {model_name}: {e} ---")
            continue

    return "Namaste ji! Hotel Ganga Palace me aapka swagat hai. Batayein kaise help kar sakta hu?"
