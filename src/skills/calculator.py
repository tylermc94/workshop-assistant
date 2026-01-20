from word2number import w2n

def parse_calc_expression(expression): #parses plain English math expressions into evaluable strings
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
        
        try:
            number = w2n.word_to_num(token)
            math_expression.append(str(number))
        except ValueError:
            if token in operators.values():
                math_expression.append(token)
    
    return ' '.join(math_expression)

def evaluate_expression(expression):
    """
    Evaluates a mathematical expression safely.
    
    Args:
        expression (str): The mathematical expression (e.g., "2 + 2").
        
    Returns:
        float: The result of the evaluation.
    """
    try:
        # Using eval in a controlled manner
        allowed_names = {"__builtins__": None}
        result = eval(expression, allowed_names, {})
        return result
    except Exception as e:
        raise ValueError(f"Error evaluating expression: {e}")

def calculate(expression):
    """
    Calculates the result of a natural language arithmetic expression.
    
    Args:
        expression (str): The arithmetic expression in natural language (e.g., "two plus two").
        
    Returns:
        float: The result of the calculation.
    """
    math_expression = parse_calc_expression(expression)
    result = evaluate_expression(math_expression)
    return result