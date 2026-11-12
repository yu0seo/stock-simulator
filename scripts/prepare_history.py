"""Download and validate immutable price/disclosure snapshots. Never prints API keys."""
import argparse
import hashlib
import json
import re
import sys
import time
import io
import shutil
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.core.config import settings
from app.services.catalog import STOCKS


def dart(client, endpoint, **params):
    try:
        r = client.get('https://opendart.fss.or.kr/api/' + endpoint + '.json',
                       params={'crtfc_key': settings.opendart_api_key, **params})
        r.raise_for_status()
        data = r.json()
        if data.get('status') == '013':
            return {'list': []}
        if data.get('status') != '000':
            raise RuntimeError('OpenDART status: ' + str(data.get('status')))
        return data
    except Exception:
        raise RuntimeError('OpenDART request failed; check API key, allowed IP and quota.') from None
    finally:
        time.sleep(0.15)


def collect_reports(client, stock, year):
    filings = {}
    page = 1
    while True:
        result = dart(client, 'list', corp_code=stock['corp'], bgn_de=f'{year-1}0101',
                      end_de=f'{year}1231', last_reprt_at='N', pblntf_ty='A', page_count=100, page_no=page)
        filings.update({x['rcept_no']: x for x in result['list']})
        if page >= result.get('total_page', 1):
            break
        page += 1
    reports = []
    periods = [('11013', '03-31'), ('11012', '06-30'), ('11014', '09-30'), ('11011', '12-31')]
    for y in (year - 1, year):
        for code, end in periods:
            if y == year and code == '11011':
                continue  # This annual report cannot have been published during the game year.
            for division in ('CFS', 'OFS'):
                rows = dart(client, 'fnlttSinglAcntAll', corp_code=stock['corp'], bsns_year=y,
                            reprt_code=code, fs_div=division)['list']
                if not rows:
                    continue
                receipts = {x.get('rcept_no') for x in rows}
                if len(receipts) != 1:
                    break
                receipt = next(iter(receipts))
                filing = filings.get(receipt)
                # The API can return a later correction. Never relabel it as the original filing.
                if not filing or not re.fullmatch(r'\d{14}', receipt or ''):
                    break
                stamp = filing['rcept_dt']
                published = f'{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}'
                reports.append({'title': filing['report_nm'], 'receipt': receipt,
                                'published_at': published, 'period_end': f'{y}-{end}',
                                'year': y, 'report_code': code, 'statement': division,
                                'url': 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + receipt,
                                'rows': rows})
                break
    return reports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--year', type=int, default=settings.game_year)
    parser.add_argument('--prices-only', action='store_true', help='Explicitly prepare a dataset without financial reports')
    parser.add_argument('--expand', action='store_true', help='Reuse verified old prices/reports and add missing stocks without changing existing prices')
    args = parser.parse_args()
    year = args.year
    if not 2016 <= year <= 2100:
        raise RuntimeError('Unsupported year')
    import FinanceDataReader as fdr
    import requests
    import httpx
    original = requests.sessions.Session.request
    def bounded_request(session, method, url, **kwargs):
        kwargs.setdefault('timeout', 45)
        return original(session, method, url, **kwargs)
    requests.sessions.Session.request = bounded_request
    folder = Path(settings.historical_data_path) / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    previous = None
    old_reports = {}
    if args.expand and (folder/'manifest.json').exists():
        previous = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        digest = hashlib.sha256()
        for name, expected in previous['files'].items():
            if Path(name).name != name:
                raise RuntimeError('Invalid old snapshot path')
            raw = (folder/name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise RuntimeError('Old snapshot failed verification; expansion stopped')
            digest.update(name.encode()+raw)
        old_id = digest.hexdigest()[:20]
        backup = folder/'snapshots'/old_id
        backup.mkdir(parents=True, exist_ok=True)
        for name in [*previous['files'], 'manifest.json']:
            shutil.copy2(folder/name, backup/name)
        old_reports = json.loads((folder/'financials.json').read_text(encoding='utf-8'))
    output = {}
    calendar = set()
    for stock in STOCKS:
        symbol = stock['symbol']
        import pandas as pd
        reused = previous and symbol+'.csv' in previous['files']
        frame = pd.read_csv(folder/(symbol+'.csv'),index_col='Date',parse_dates=True) if reused else fdr.DataReader('NAVER:' + symbol, f'{year-1}-09-01', f'{year}-12-31')
        if frame.empty or any(c not in frame for c in ('Close', 'Volume')):
            raise RuntimeError('Missing historical prices: ' + symbol)
        frame = frame[['Open', 'High', 'Low', 'Close', 'Volume']]
        if frame.index.duplicated().any() or frame.index.min().year >= year or frame.index.max().strftime('%Y-%m-%d') < f'{year}-12-20':
            raise RuntimeError('Incomplete historical prices: ' + symbol)
        if not frame['Close'].gt(0).all() or not frame['Volume'].ge(0).all():
            raise RuntimeError('Invalid historical price or volume: ' + symbol)
        frame.index.name = 'Date'
        output[symbol + '.csv'] = (folder/(symbol+'.csv')).read_bytes() if reused else frame.to_csv(date_format='%Y-%m-%d').encode('utf-8')
        calendar.update(d.strftime('%Y-%m-%d') for d, row in frame.iterrows() if row['Volume'] > 0)
        print(symbol + ': ' + str(len(frame)) + ' daily prices', flush=True)
    output['calendar.json'] = json.dumps(sorted(calendar)).encode()
    reports = {s['symbol']: old_reports.get(s['symbol'],[]) for s in STOCKS}
    if not args.prices_only:
        if not settings.opendart_api_key:
            raise RuntimeError('Set OPENDART_API_KEY, or explicitly use --prices-only.')
        with httpx.Client(timeout=40) as client:
            try:
                response = client.get('https://opendart.fss.or.kr/api/corpCode.xml',params={'crtfc_key':settings.opendart_api_key})
                response.raise_for_status()
                archive = zipfile.ZipFile(io.BytesIO(response.content))
                xml = ET.fromstring(archive.read('CORPCODE.xml'))
                codes = {x.findtext('stock_code','').strip():x.findtext('corp_code') for x in xml.findall('list')}
            except Exception:
                raise RuntimeError('Could not read the official DART corporation directory.') from None
            todo = []
            for stock in STOCKS:
                if args.expand and stock['symbol'] in old_reports:
                    continue
                corp = stock['corp'] or codes.get(stock['symbol'])
                if not corp:
                    raise RuntimeError('No DART corporation found for ' + stock['symbol'])
                todo.append({**stock,'corp':corp})
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {pool.submit(collect_reports,client,stock,year):stock['symbol'] for stock in todo}
                for future in as_completed(futures):
                    symbol = futures[future]
                    reports[symbol] = future.result()
                    print(symbol + ': ' + str(len(reports[symbol])) + ' verified financial reports', flush=True)
    output['financials.json'] = json.dumps(reports, ensure_ascii=False).encode('utf-8')
    manifest = {'year': year, 'created_at': datetime.now(timezone.utc).isoformat(),
                'source': 'FinanceDataReader / NAVER daily prices', 'calendar_source': 'union of positive-volume dates in the selected universe',
                'symbols':[s['symbol'] for s in STOCKS],
                'price_policy': 'provider historical series, no synthetic intraday prices; no separate dividends or corporate-action cashflows',
                'financial_policy': 'exact receipt matching; later corrections unavailable before their own publication date',
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in output.items()}}
    if previous:
        # This list permits a price-preserving, additive upgrade of a saved campaign.
        manifest['compatible_predecessors'] = list(dict.fromkeys(previous.get('compatible_predecessors',[])+[old_id]))
    # Download everything before replacing files; publish the manifest last.
    for name, data in output.items():
        path = folder / name
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_bytes(data)
        tmp.replace(path)
    tmp = folder / 'manifest.json.tmp'
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(folder / 'manifest.json')
    print('Prepared ' + str(year) + '. Restart the server after replacing an existing snapshot.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Third-party exceptions can contain credential-bearing URLs. Only controlled errors are printed.
        print(str(error) if isinstance(error, RuntimeError) else 'Data preparation failed. Check connectivity and provider availability.', file=sys.stderr)
        raise SystemExit(1)
