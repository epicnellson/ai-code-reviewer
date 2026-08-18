import unittest
from unittest.mock import patch, MagicMock
from reviewer.analyzer import Analyzer, DEFAULT_HOSTED_API_URL

class TestAnalyzer(unittest.TestCase):
    
    @patch('reviewer.analyzer.Groq')
    @patch('reviewer.analyzer.os.environ.get')
    def test_analyzer_initialization(self, mock_env, mock_groq):
        """Test that the Analyzer initializes correctly with API key."""
        mock_env.return_value = "fake_api_key"
        analyzer = Analyzer()
        self.assertIsNotNone(analyzer)
        
    @patch('reviewer.analyzer.os.environ.get')
    def test_analyzer_missing_api_key_falls_back_to_default(self, mock_env):
        """Test that the Analyzer falls back to DEFAULT_HOSTED_API_URL when no key/url."""
        mock_env.return_value = None
        analyzer = Analyzer()
        self.assertEqual(analyzer.api_url, DEFAULT_HOSTED_API_URL)
        self.assertIsNone(analyzer.client)

if __name__ == "__main__":
    unittest.main()
