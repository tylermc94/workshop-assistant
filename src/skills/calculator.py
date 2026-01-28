from word2number import w2n
import logging

logger = logging.getLogger(__name__)

def parse_calc_expression(expression):
    """Parses plain English math expressions into evaluable strings"""
    logger.info(f"Parsing expression: {expression}")
    
    # Remove commas from numbers (1,576 -> 1576)
    expression = expression.replace(',', '')
    
    # Fix common speech recognition errors for math
    homophones = {
        'for': 'four',
        'to': 'two',
        'too': 'two',
        'ate': 'eight',
        'won': 'one'
    }
    
    for wrong, right in homophones.items():
        expression = expression.replace(wrong, right)
    
    operators = {
        'plus': '+',
        'minus': '-',
        'times': '*',
        'multiplied by': '*',
        'divided by': '/',
        'over': '/'
    }
    
    for word, symbol in operators.items():
        expression = expression.replace(word, f' {symbol} ')
    
    tokens = expression.split()
    math_expression = []
    
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        
        # Try to parse as digit first
        try:
            number = int(token)
            math_expression.append(str(number))
            continue
        except ValueError:
            pass
        
        # Then try word2number
        try:
            number = w2n.word_to_num(token)
            math_expression.append(str(number))
        except ValueError:
            if token in operators.values():
                math_expression.append(token)
    
    result = ' '.join(math_expression)
    logger.info(f"Parsed to: {result}")
    return result

def evaluate_expression(expression):
    """Evaluates a mathematical expression safely"""
    try:
        allowed_names = {"__builtins__": None}
        result = eval(expression, allowed_names, {})
        logger.info(f"Evaluated '{expression}' = {result}")
        return result
    except Exception as e:
        raise ValueError(f"Error evaluating expression: {e}")

def calculate(expression):
    """Calculates the result of a natural language arithmetic expression"""
    math_expression = parse_calc_expression(expression)
    result = evaluate_expression(math_expression)
    return result