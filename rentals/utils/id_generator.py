"""Reusable Luhn check-digit helpers for independent document identifiers."""

import secrets


def generate_luhn_number(num_digits):
    """
    Generate a random number string of specified length that passes the Luhn algorithm.
    The last digit is a check digit.
    """
    if num_digits < 2:
        raise ValueError("Length must be at least 2 to include a check digit.")

    base = [secrets.randbelow(10) for _ in range(num_digits - 1)]
    check_digit = calculate_luhn_check_digit(base)
    return ''.join(map(str, base + [check_digit]))

def calculate_luhn_check_digit(digits):
    """
    Calculate the Luhn check digit for a list of digits.
    This digit ensures the full number passes the Luhn checksum.
    """
    total = 0
    reverse_digits = digits[::-1]

    for i, digit in enumerate(reverse_digits):
        if i % 2 == 0:
            doubled = digit * 2
            total += doubled if doubled < 10 else sum(map(int, str(doubled)))
        else:
            total += digit

    return (10 - (total % 10)) % 10
