# Memory Extraction Prompt

Extract factual information about the user from the conversation.

## What to Extract

- **Personal info**: name, age, location, occupation, timezone
- **Preferences**: preferred city for weather, language preference, communication style
- **Recurring topics**: things the user asks about frequently

## Format

Return each fact as a single line, e.g.:
- User's name is Alice
- User lives in Tokyo
- User prefers Celsius for temperature

Only extract facts that the user has explicitly stated. Do NOT infer or guess.
