"""Offline browser proof for all three local agents; no real CLI or model calls."""
from tests.browser.browser_learning_view import main

if __name__ == '__main__':
    main(timeline_test=True, agent_test=True)
