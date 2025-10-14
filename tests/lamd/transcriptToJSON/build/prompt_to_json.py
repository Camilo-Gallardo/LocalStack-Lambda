PROMPT_TO_JSON = """You are an expert in technical content processing and information synthesis. Analyze the provided document text and generate a structured summary in the exact JSON format specified below.

**Important:** All outputs (description, summary, keywords, topics, and conclusion) must be written in Spanish.

**Required JSON Template:**
{{
    "$entidad": "{index}",
    "$documents": [
        {{
            "title": "{video_title}",
            "type": "mp4",
            "key": "{index}/video/{video_title}.mp4"
        }}
    ],
    "{index}_title": "[BRIEF_TITLE]",
    "{index}_description": "[BRIEF_DESCRIPTION]",
    "{index}_keywords": "[KEYWORDS_SEPARATED_BY_COMMAS]",
    "{index}_summary": "[GENERAL_SUMMARY]", 
    "{index}_topics": [
        {{
            "key_1": ["CONTENT 1"]
        }},
        {{
            "key_2": ["CONTENT 2"]
        }}
    ],
    "{index}_conclusion": "[GENERAL_CONCLUSION]"
}}

**Your Tasks:**

1. **General Analysis:** Read the entire text thoroughly and understand the main topic, subtopics, key concepts, and identify any examples provided.

2. **Complete Metadata:**
   - Create a concise title for the session (5-7 words, in Spanish)
   - Generate a concise description (1-2 sentences) explaining what the document is about (in Spanish)
   - Create a comprehensive summary (3-5 sentences) synthesizing the main points (in Spanish)
   - Extract 5-10 relevant keywords (comma-separated, in Spanish)

3. **Identify Topics:**
   - Identify all main topics and subtopics discussed in the document
   - Ensure the entire document content is reflected in the summary
   - For each topic, create an entry in the "temas" array using this format:
   ```
   {{
       "Topic_Name_With_Underscores": ["2-3 comprehensive paragraphs summarizing the topic including key points and important concepts (in Spanish)", "Example mentioned (if any, in Spanish)"]
   }}
   ```
   - Topic names should be concise and descriptive
   - If explicit examples exist for a topic, include them as the second array element (in Spanish)
   - Each topic should be a separate object in the array

4. **Conclusion:**
   - Generate a conclusion (3-5 sentences) synthesizing the main findings and the importance of the content (in Spanish)

**Critical Rules:**
- Return ONLY valid JSON that can be parsed
- Maintain the exact format specified in the template
- Use clear and professional language (in Spanish)
- Ensure all fields are complete and properly filled
- Replace bracketed placeholders with extracted/generated information (in Spanish)
- Convert topic titles by replacing spaces with underscores (_)
- The summary must be comprehensive and reflect ALL document content
- Do not include any text outside the JSON response
- Ensure proper JSON escaping for quotes and special characters

**Document Text to Analyze:**
{text}

Respond with only the completed JSON structure:"""
