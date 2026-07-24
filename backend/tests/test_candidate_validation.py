from agent.validation import validate_candidate_source


def diagnostic_codes(report):
    return {item["code"] for item in report["diagnostics"]}


def test_standard_quantconnect_source_passes_bounded_preflight():
    source = """from AlgorithmImports import *
from alphaforge_base import AlphaForgeBaseAlgorithm

class UserStrategy(AlphaForgeBaseAlgorithm):
    def initialize(self):
        self.symbol = self.add_equity("MSFT", Resolution.DAILY).symbol

    def on_data(self, data):
        self.set_holdings(self.symbol, 0.8)
"""
    for track in ("Traditional", "ML", "Hybrid"):
        report = validate_candidate_source(source, track)
        assert report["status"] == "passed"
        assert report["diagnostics"] == []
        assert len(report["source_sha256"]) == 64
        assert len(report["semantic_sha256"]) == 64


def test_preflight_does_not_use_track_keywords_as_admission_rules():
    source = """class UserStrategy:
    def initialize(self):
        self.model = object()
    def on_data(self, data):
        self.liquidate()
"""
    assert validate_candidate_source(source, "Traditional")["status"] == "passed"
    assert validate_candidate_source(source, "Hybrid")["status"] == "passed"


def test_syntax_error_is_rejected():
    report = validate_candidate_source("def broken(:\n    pass\n", "ML")
    assert report["status"] == "failed"
    assert diagnostic_codes(report) == {"PYTHON_SYNTAX"}
    assert report["semantic_sha256"] is None


def test_clear_file_process_and_network_capabilities_are_rejected():
    source = """import os
import requests
import subprocess

def run():
    open("secret.txt")
"""
    report = validate_candidate_source(source, "Traditional")
    assert report["status"] == "failed"
    assert diagnostic_codes(report) == {"UNSAFE_IMPORT", "UNSAFE_CALL"}


def test_normal_scientific_imports_and_order_apis_are_not_blacklisted():
    source = """import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

class UserStrategy:
    def initialize(self):
        self.model = GradientBoostingRegressor()
    def on_data(self, data):
        self.market_order(self.symbol, 1)
"""
    assert validate_candidate_source(source, "ML")["status"] == "passed"
