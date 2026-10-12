Hotel Ganga View WACRM-style AI comparison lab

Standalone Node 20+ app on an isolated GitHub branch and Render service. This extracts the direct AI reply + knowledge retrieval + conversation-history approach from the separately supplied open-source wacrm archive (upstream ArnasDon/wacrm, MIT License). It is not the complete CRM.

Complete original hotel_data.txt is copied from Ganga Bot at build time into this branch. Does NOT use Ganga Bot's WhatsApp, database, Sheets, API keys, webhook, or operational functions.

Run npm test then npm start. In the browser, paste your own temporary AI provider API key. Keys are never persisted by the application. Only pre-approved Groq/Cohere/Gemini/OpenAI HTTPS endpoints are called.
