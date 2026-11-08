import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='SlicePoint pretrained 3D aorta baseline')
    sub = parser.add_subparsers(dest='command', required=True)
    dl = sub.add_parser('download')
    dl.add_argument('--output', type=Path, default=Path('data'))
    dl.add_argument('--release', choices=['practice', 'sunday'], default='practice')
    dl.add_argument('--hospital', help='For example hospital_a; omit for all released hospitals')
    dl.add_argument('--tables-only', action='store_true')
    pred = sub.add_parser('predict')
    pred.add_argument('--ct', type=Path, required=True)
    pred.add_argument('--reference', type=Path)
    pred.add_argument('--output', type=Path, required=True)
    cohort = sub.add_parser('evaluate')
    cohort.add_argument('--hospital', type=Path, required=True)
    cohort.add_argument('--vendor-masks', type=Path)
    cohort.add_argument('--output', type=Path, required=True)
    cohort.add_argument('--limit', type=int)
    for p in [pred, cohort]:
        p.add_argument('--fast', action='store_true', help='3mm preview; keep off for final evaluation')
        p.add_argument('--device', choices=['gpu', 'cpu'], default='gpu')
    compare = sub.add_parser('compare')
    compare.add_argument('--prediction', type=Path, required=True)
    compare.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'download':
        from .download import download
        # Avoid dumping signed URLs in Azure tracebacks.
        try:
            download(args.output, args.release, args.hospital, args.tables_only)
        except Exception as exc:
            parser.exit(1, f'Download failed ({type(exc).__name__}). Check link expiry, access and archive layout.\n')
        return
    from .core import compare_masks, predict
    if args.command == 'compare':
        print(json.dumps(compare_masks(args.prediction, args.reference), indent=2))
    elif args.command == 'predict':
        mask, result = predict(args.ct, args.output, fast=args.fast, device=args.device)
        if args.reference:
            result['metrics'] = compare_masks(mask, args.reference)
        (args.output / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
    else:
        from .cohort import evaluate
        if args.limit is not None and args.limit < 1:
            parser.error('--limit must be positive')
        print(json.dumps(evaluate(args.hospital, args.output, vendor_masks=args.vendor_masks,
                                 fast=args.fast, device=args.device, limit=args.limit), indent=2))


if __name__ == '__main__':
    main()
