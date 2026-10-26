"""Classify nested Live exceptions without losing the service's root error."""
def leaves(error):
    children = getattr(error, 'exceptions', ())
    if children:
        for child in children:
            yield from leaves(child)
    else:
        yield error


def error_text(error):
    return ' | '.join(f'{type(item).__name__}: {item}' for item in leaves(error))


def is_aborted(error):
    return any((getattr(item, 'code', None) == 1008 or '1008' in str(item)) and
               'abort' in str(item).lower()
               for item in leaves(error))
