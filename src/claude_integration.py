def ask_claude(question):
    """
    Send a question to Claude API and return the response.
    Logs the query for analysis.
    """
    logger.info(f"Sending to Claude: {question}")
    
    # Log query to file for pattern analysis
    log_query(question)
    
    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            temperature=CLAUDE_TEMPERATURE,
            system="""You are Forge, a helpful workshop assistant. Be conversational and friendly like a helpful colleague, not robotic. 

Give concise, practical answers - just the key info needed, skip disclaimers and caveats unless critical. Respond in 1-2 sentences for simple questions, 2-3 for complex ones.

Examples:
- "What's the best temperature for PLA?" → "200 to 210 degrees Celsius works great for most PLA filaments."
- "Who won the Super Bowl?" → "The Chiefs beat the 49ers 25-22 in overtime at Super Bowl 58."

Be helpful and direct, not overly cautious.""",
            messages=[
                {"role": "user", "content": question}
            ]
        )
        
        response = message.content[0].text
        logger.info(f"Claude response: {response}")
        
        # TODO: Track token usage for budget
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        logger.info(f"Tokens used - Input: {input_tokens}, Output: {output_tokens}")
        
        return response
        
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return "Sorry, I couldn't reach Claude right now. Please try again."
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return "Sorry, something went wrong."