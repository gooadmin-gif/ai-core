History_Index.md

# History Index Management Rules v1.1

## 1. Core Philosophy
Treat long-term memory as a static index log to prevent unnecessary interference and context noise during reasoning.
*Note: These rules define the output format for index records. Actual persistent storage (files, databases, notes, etc.) must be prepared separately (see Section 6).*

## 2. Log Format
Output one record per line using a half-width pipe `|` as the delimiter.
*Do not include half-width `|` inside the Summary, Extra, or Chunk fields (replace any occurrences with full-width `｜` or `/`).*

tttt|zzz-xxxx|Summary|Extra|Chunk

- tttt: Turn number (4-digit zero-padded sequential integer starting from 0001)
- zzz: Theme code (see Section 3)
- xxxx: Intra-theme sequence number (4-digit zero-padded). Increment by +1 while the same theme code continues consecutively; reset to 0001 whenever the theme code changes (even if that theme appeared earlier in the chat)
- Summary: Static summary within 200 characters
- Extra: Metadata such as the chat's primary objective, structured data IDs, or script bodies (leave empty if none)
- Chunk: Key takeaways for lookup/reference rather than verbatim text (target: within 200 characters). Trace original text via reference ID (`tttt`)

## 3. Theme Codes (zzz)
- 000: Small talk / Greetings / Unknown / General (excluded during re-reads)
- 700: Work / Business (General)
- 710: Work / Business (Design & Development)
- 720: Work / Business (Documentation & Coordination)
- 800: Consultation / Brainstorming
- 810: Review / Proofreading
- 900: Prompts / System Definitions
- 910: Scripts / Code
- 999: Unclassified (use this instead of 000 when uncertain)

## 4. Primary Objective of the Chat
- If a specific objective or request is provided in Turn 1 (beyond pasting these rules): Record `Objective=<description>` in the Extra field.
- If Turn 1 contains only these rules: Record `Objective=Undetermined` in Turn 1, and update to `Objective=<description>` once a specific objective is given in Turn 2.
- If no specific objective appears in either Turn 1 or Turn 2: Record `Objective=None`.
- If the objective emerges later or changes in subsequent turns: Record the new `Objective=<new>` in the Extra field alongside `Previous=<old>`.

## 5. Output & Re-read Timing
- Output one record for the current turn at the end of every response.
- Do not output a record on turns where the user explicitly states "No log" (`ログ不要`).
- Whenever the turn number (`tttt`) reaches a multiple of 10 (0010, 0020, 0030...), re-read past logs in strict chronological order (oldest first: 0001, 0002, 0003...) before generating your response.
  - During re-reads, exclude records with theme code `000`, and review the latest `Objective` (including any `Previous` history) together with the logs.
  - Reading logs in reverse order (newest first) is strictly prohibited.

## 6. Operational Notes
- Within a single chat session, history already exists in the context window, so the effect of re-reading is limited.
- Across separate chat sessions, save the generated logs and the latest `Objective` to an external file or note, and paste them at the beginning of the next session.
- Because turn numbering (`tttt`) may drift in very long chats, normalize or re-index sequence numbers via an external script if needed.

## 7. Disclaimer & Compatibility
- Format adherence has been verified on Gemini and ChatGPT (adherence is limited on Claude).
- Persistence of memory and exact numbering are not guaranteed; behavior may vary with model updates.
- Use at your own risk.
