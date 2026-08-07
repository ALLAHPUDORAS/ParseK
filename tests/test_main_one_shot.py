import os
import unittest
from unittest.mock import patch

from src import main as main_module


class MainOneShotTests(unittest.TestCase):
    @patch("src.main.run_pipeline")
    def test_one_shot_cli_flag_runs_once_and_exits(self, mock_run_pipeline):
        args = unittest.mock.Mock()
        args.one_shot = True
        args.headless = False
        args.max_leads = 1
        args.export_json = False
        args.export_csv = False
        args.export_text = False

        with patch("src.main.parse_args", return_value=args):
            main_module.main()

        mock_run_pipeline.assert_called_once_with(args)

    @patch("src.main.run_pipeline")
    def test_one_shot_env_var_runs_once_and_exits(self, mock_run_pipeline):
        args = unittest.mock.Mock()
        args.one_shot = False
        args.headless = False
        args.max_leads = 1
        args.export_json = False
        args.export_csv = False
        args.export_text = False

        with patch.dict(os.environ, {"ONE_SHOT": "1"}):
            with patch("src.main.parse_args", return_value=args):
                main_module.main()

        mock_run_pipeline.assert_called_once_with(args)


if __name__ == "__main__":
    unittest.main()
