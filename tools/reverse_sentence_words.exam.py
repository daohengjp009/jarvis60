# FUNCTION: reverse_words(sentence: str) -> str

# Normal case
assert reverse_words('hello world foo') == 'foo world hello'

# Single word
assert reverse_words('hello') == 'hello'

# Two words
assert reverse_words('hello world') == 'world hello'

# Empty string
assert reverse_words('') == ''

# Multiple spaces treated as single-word tokens (standard split behavior)
assert reverse_words('one two three four') == 'four three two one'

# Sentence with punctuation preserved as part of words
assert reverse_words('good morning world') == 'world morning good'