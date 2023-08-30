

import logging
import re
from typing import List, Tuple


def _text_substitution(s):
    """Perform text substitutions on the string s, e.g. transcibing things like 'new line' to '\n'."""
    format_commands = [
        (['new', 'line'], '\n'),
        (['new', 'paragraph'], '\n\n'),
        # this is a common mistranslation of new paragraph
        (['you', 'paragraph'], '\n\n'),
        (['new', 'horizontal', 'line'], '\n\n---\n\n'),
        (['new', 'to', 'do'], ' #TODO '),
        (['new', 'to-do'], ' #TODO '),
    ]

    direct_substitutions : List[Tuple[str, str]] = [
        ('name ?ear',   'IA'),
        ('name ?ia',    'IA'),
        ('name ?jack',  'JACK'),
        ('name ?g',     'JI'),
        ('name ?Karel', 'Kaarel'),
    ]

    symbols = [
        (['symbol', 'open', 'parentheses'], ' ('),
        (['symbol', 'close', 'parentheses'], ') '),
        (['symbol', 'open', 'parenthesis'], ' ('),
        (['symbol', 'close', 'parenthesis'], ') '),
        (['symbol', 'open', 'bracket'], ' ['),
        (['symbol', 'close', 'bracket'], '] '),
        (['symbol', 'open', 'curly', 'brace'], ' {'),
        (['symbol', 'close', 'curly', 'brace'], '} '),
        (['symbol', 'full', 'stop'], '. '),
        (['symbol', 'period'], '. '),
        (['symbol', 'exclamation', 'mark'], '! '),
        (['symbol', 'comma'], ', '),
        (['symbol', 'semicolon'], '; '),
        (['symbol', 'Question', 'mark'], '? '),
        (['symbol', 'hyphen'], '-'),
        (['symbol', 'dash'], '-'),
        (['symbol', 'under', 'score'], '_'),
        (['symbol', 'back', 'slash'], '\\\\'),
        (['symbol', 'dollar', 'sign'], '$'),
        (['symbol', 'percent', 'sign'], '%'),
        (['symbol', 'ampersand'], '&'),
        (['symbol', 'asterisk'], '*'),
        (['symbol', 'at', 'sign'], '@'),
        (['symbol', 'caret'], '^'),
        (['symbol', 'tilde'], '~'),
        (['symbol', 'pipe'], '|'),
        (['symbol', 'forward', 'slash'], '/'),
        (['symbol', 'colon'], ': '),
        (['symbol', 'double', 'quote'], '"'),
        (['symbol', 'single', 'quote'], "'"),
        (['symbol', 'less', 'than', 'sign'], '<'),
        (['symbol', 'greater', 'than', 'sign'], '>'),
        (['symbol', 'plus', 'sign'], '+'),
        (['symbol', 'equals', 'sign'], '='),
        (['symbol', 'hash', 'sign'], '#'),
    ]

    format_commands.extend(symbols)

    commands_help = "\n".join([' '.join(c) + ": '" + re.sub('\n', '⏎', t) + "'" for c,t in format_commands])
    if s.lower().strip().replace(' ', '').replace(',', '').replace('.', '') == ''.join(['command', 'print', 'help']):
        logging.debug('printing help')
        return commands_help

    commands_1 = []
    for p,r in format_commands:
        commands_1.append((''.join(p), r))
        commands_1.append((' '.join(p), r))
    commands_2 = []
    for p,r in commands_1:
        commands_2.append((f'{p}. ', r))
        commands_2.append((f'{p}, ', r)) 
        commands_2.append((f'{p}.', r))
        commands_2.append((f'{p},', r))
        commands_2.append((p, r))
    commands_3 = []
    for p,r in commands_2:
        commands_3.append((f' {p}', r))
        commands_3.append((f'{p}', r))

    for p,r in direct_substitutions:
        s = re.sub(p, r, s, flags=re.IGNORECASE)

    # Commands to insert headings
    for i,e in enumerate(['one', 'two', 'three', 'four', 'five', 'six']):
        format_commands.append((['new', 'heading', e], f'\n\n'+ ("#" * (i)) + ' '))
        format_commands.append((['new', 'heading', str(i)], f'\n\n'+ ("#" * (i)) + ' '))

    # Insert bullet points, stripping punctuation and capitalizing the first letter
    s = re.sub('[,.!?]? ?new[,.!?]? ?bullet[,.!?]? ?([a-z])?', lambda p: f'\n- {p.group(1).upper() if p.group(1) else ""}', s, flags=re.IGNORECASE)
    # Trim trailing punctuation. This is needed for the last line.
    s = re.sub('^(\s*- .*)[,.!?]+ *$', lambda p: f"{p.group(1)}", s, flags=re.MULTILINE)

    for p,r in commands_3:
        s = re.sub(p, r, s, flags=re.IGNORECASE)

    return s

def process_transcription(args, text):
    text = text.strip()
    text = text.replace('\n', ' ')
    if not args.no_postprocessing:
        text = _text_substitution(text)
    if args.start_lowercase:
        if len(text) >= 2:
            text = text[0].lower() + text[1:]
        elif len(text) == 1:
            text = text[0].lower()
    text = re.sub("\\'", "'", text)
    text = re.sub("thank you\. ?$", "", text, flags=re.IGNORECASE)
    text = re.sub(". \)", ".\)", text)
    text = re.sub("[,.!?]:", ":", text)
    # Add a space after the text such that the cursor is at the correct 
    # position to again insert the next piece of transcribed text. 
    text.rstrip()
    text += ' '
    return text
