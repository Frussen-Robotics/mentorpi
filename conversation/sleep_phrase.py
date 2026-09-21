"""Detect a standalone sleep phrase in user transcript fragments."""
import re


class SleepRequested(Exception):
    pass


def words(text):
    return re.findall(r"[^\W_]+", text.casefold())


class SleepPhraseDetector:
    def __init__(self, phrase="notte ruben"):
        self.phrase = words(phrase)
        if not self.phrase:
            raise ValueError("La frase di chiusura è vuota")
        self.text = ""
        self.last_end = None
        self.overflow = False

    def feed(self, delta, start_ms, end_ms):
        if not delta:
            return False

        # Start a new phrase after at least one second without transcript.
        if self.last_end is not None and start_ms - self.last_end >= 1000:
            self.text = ""
            self.overflow = False

        self.last_end = end_ms

        if self.overflow:
            return False

        self.text += delta
        if len(self.text) > 512:
            self.text = ""
            self.overflow = True
            return False

        return words(self.text) == self.phrase
