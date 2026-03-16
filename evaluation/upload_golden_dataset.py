from __future__ import annotations

import argparse

from evaluation.golden_dataset import load_golden_examples, to_dataset_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload golden dataset to Phoenix.")
    parser.add_argument("--name", default="cortex-analyst-golden", help="Phoenix dataset name")
    parser.add_argument("--path", default=None, help="Path to YAML examples")
    args = parser.parse_args()

    try:
        import phoenix as px
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("Phoenix SDK is required. Install `arize-phoenix`.") from error

    examples = load_golden_examples(args.path)
    records = to_dataset_records(examples)
    try:
        import pandas as pd
    except Exception as error:  # noqa: BLE001
        raise RuntimeError("pandas is required for dataset upload.") from error
    client = px.Client()
    client.upload_dataset(
        dataset_name=args.name,
        dataframe=pd.DataFrame(records),
    )
    print(f"Uploaded {len(records)} records to dataset '{args.name}'.")


if __name__ == "__main__":
    main()
