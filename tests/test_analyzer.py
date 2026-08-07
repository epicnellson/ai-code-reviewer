import unittest
from unittest.mock import patch, MagicMock
from reviewer.analyzer import Analyzer

class TestAnalyzer(unittest.TestCase):
    
    @patch('reviewer.analyzer.Groq')
    @patch('reviewer.analyzer.os.environ.get')
    def test_analyzer_initialization(self, mock_env, mock_groq):
        """Test that the Analyzer initializes correctly with API key."""
        mock_env.return_value = "fake_api_key"
        analyzer = Analyzer()
        self.assertIsNotNone(analyzer)
        
    @patch('reviewer.analyzer.os.environ.get')
    def test_analyzer_missing_api_key(self, mock_env):
        """Test that the Analyzer raises an error when API key is missing."""
        mock_env.return_value = None
        with self.assertRaises(ValueError):
            Analyzer()

if __name__ == "__main__":
    unittest.main()
