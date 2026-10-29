#!/usr/bin/env python3
"""
Test script to validate the ECMWF Medium-Range Integration

Tests:
1. Package installations
2. Script creation
3. File structure
4. GitHub workflow modification
"""

import os
import sys
from pathlib import Path

def test_package_installed():
    """Test that ecmwf-opendata package is installed."""
    try:
        import ecmwf.opendata
        print("✅ ecmwf-opendata package is installed")
        return True
    except ImportError as e:
        print(f"❌ ecmwf-opendata package not installed: {e}")
        return False


def test_download_script():
    """Test that download_medium_range.py exists and is valid Python."""
    script_path = Path("download_medium_range.py")
    if not script_path.exists():
        print("❌ download_medium_range.py not found")
        return False
    
    # Test syntax compilation
    import py_compile
    try:
        py_compile.compile(script_path, doraise=True)
    except Exception as e:
        print(f"❌ download_medium_range.py has syntax errors: {e}")
        return False
    
    try:
        with open(script_path) as f:
            content = f.read()
            if "def download_instantaneous_variables" not in content:
                print("❌ download_medium_range.py missing download_instantaneous_variables function")
                return False
            if "def download_accumulated_variables" not in content:
                print("❌ download_medium_range.py missing download_accumulated_variables function")
                return False
            if '"2t", "msl", "10u", "10v", "d2m"' not in content and "'2t', 'msl', '10u', '10v', 'd2m'" not in content:
                print("❌ download_medium_range.py missing expected instantaneous variables")
                return False
            if '"tp", "tpg1", "tpg5", "10fg"' not in content and "'tp', 'tpg1', 'tpg5', '10fg'" not in content:
                print("❌ download_medium_range.py missing expected accumulated variables")
                return False
            print("✅ download_medium_range.py exists and contains variable separation")
            return True
    except Exception as e:
        print(f"❌ Error reading download_medium_range.py: {e}")
        return False


def test_plot_script():
    """Test that plot_medium_range.py exists."""
    script_path = Path("plot_medium_range.py")
    if not script_path.exists():
        print("❌ plot_medium_range.py not found")
        return False
    print("✅ plot_medium_range.py exists")
    return True


def test_requirements_updated():
    """Test that requirements.txt includes ecmwf-opendata."""
    req_path = Path("requirements.txt")
    if not req_path.exists():
        print("❌ requirements.txt not found")
        return False
    
    with open(req_path) as f:
        content = f.read()
        if "ecmwf-opendata" not in content:
            print("❌ requirements.txt doesn't include ecmwf-opendata")
            return False
    
    print("✅ requirements.txt includes ecmwf-opendata")
    return True


def test_workflow_updated():
    """Test that GitHub workflow includes medium-range download."""
    workflow_path = Path(".github/workflows/daily_download2.0.yml")
    if not workflow_path.exists():
        print("❌ Workflow file not found")
        return False
    
    with open(workflow_path) as f:
        content = f.read()
        if "download_medium_range.py" not in content:
            print("❌ Workflow doesn't include download_medium_range.py")
            return False
        if "plot_medium_range.py" not in content:
            print("❌ Workflow doesn't include plot_medium_range.py")
            return False
    
    print("✅ GitHub workflow includes medium-range steps")
    return True


def test_variable_separation():
    """Verify that the medium-range download properly separates variable types."""
    script_path = Path("download_medium_range.py")
    with open(script_path) as f:
        content = f.read()
    
    checks = {
        "Instantaneous function exists": "def download_instantaneous_variables" in content,
        "Accumulated function exists": "def download_accumulated_variables" in content,
        "Probability function exists": "def download_probability_variables" in content,
        "Source AWS": 'source="aws"' in content,
        "Model IFS": 'model="ifs"' in content,
        "Stream oper": '"stream": "oper"' in content,
        "Stream enfo": '"stream": "enfo"' in content,
        "Deterministic type": '"type": "fc"' in content,
        "Probability type": '"type": "ep"' in content,
        "0.1 degree resolution": 'RESOLUTION = "0p1"' in content,
        "3-hourly steps": 'list(range(0, 241, 3))' in content,
        "24-hour accumulations": 'f"{24 * i}-{24 * (i + 1)}"' in content,
        "12-hour probability ranges": 'f"{12 * i}-{12 * i + 24}"' in content,
    }
    
    all_passed = True
    for check_name, result in checks.items():
        if result:
            print(f"✅ {check_name}")
        else:
            print(f"❌ {check_name}")
            all_passed = False
    
    return all_passed


def main():
    """Run all validation tests."""
    print("=" * 70)
    print("ECMWF Medium-Range Integration - Validation Suite")
    print("=" * 70)
    print()
    
    tests = [
        ("Package Installation", test_package_installed),
        ("Download Script", test_download_script),
        ("Plot Script", test_plot_script),
        ("Requirements File", test_requirements_updated),
        ("GitHub Workflow", test_workflow_updated),
        ("Variable Separation", test_variable_separation),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n🧪 Running: {test_name}")
        print("-" * 70)
        result = test_func()
        results.append((test_name, result))
    
    print()
    print("=" * 70)
    print("📊 Test Summary")
    print("=" * 70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print()
    if passed == total:
        print(f"🎉 All {total} tests passed! Integration is ready.")
        return 0
    else:
        failed = total - passed
        print(f"⚠️  {failed} test(s) failed. Please review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
