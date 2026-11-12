"""Immutable local historical snapshots; never sends future prices to the client."""
import bisect
import csv
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from fastapi import HTTPException
from app.core.config import settings
from app.services.catalog import STOCKS, BY_SYMBOL


class HistoricalMarket:
    def __init__(self):
        self.cache = {}

    def dataset(self, year):
        root = Path(settings.historical_data_path) / str(year)
        key = str(root)
        if key in self.cache:
            return self.cache[key]
        try:
            manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
            content = {}
            digest = hashlib.sha256()
            for filename, expected in manifest['files'].items():
                if Path(filename).name != filename:
                    raise ValueError('Invalid snapshot path')
                raw = (root / filename).read_bytes()
                if hashlib.sha256(raw).hexdigest() != expected:
                    raise ValueError('Snapshot changed')
                digest.update(filename.encode() + raw)
                content[filename] = raw
            prices = {}
            for symbol in BY_SYMBOL:
                rows = list(csv.DictReader(content[symbol + '.csv'].decode('utf-8-sig').splitlines()))
                series = []
                for row in rows:
                    day = date.fromisoformat(row['Date']).isoformat()
                    close, volume = float(row['Close']), float(row['Volume'])
                    if not math.isfinite(close) or close <= 0 or not math.isfinite(volume) or volume < 0:
                        raise ValueError('Invalid quote')
                    series.append({'date': day, 'value': close, 'volume': volume})
                days = [x['date'] for x in series]
                if days != sorted(set(days)) or not days or days[0] >= f'{year}-01-01' or not f'{year}-12-20' <= days[-1] <= f'{year}-12-31':
                    raise ValueError('Incomplete year')
                prices[symbol] = (days, series)
            calendar = json.loads(content['calendar.json'])
            if calendar != sorted(set(calendar)) or not calendar:
                raise ValueError('Invalid calendar')
            financials = json.loads(content['financials.json'])
            result = {'prices': prices, 'calendar': calendar, 'financials': financials,
                      'id': digest.hexdigest()[:20], 'manifest': manifest}
            self.cache[key] = result
            return result
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, f'{year}년 과거 데이터가 없거나 검증되지 않았어요. README의 데이터 준비 절차를 실행해주세요.') from None

    def status(self, year):
        try:
            ds = self.dataset(year)
            return {'ready': True, 'dataset_id': ds['id'], 'financial_reports': sum(len(v) for v in ds['financials'].values()),
                    'source': ds['manifest'].get('source', 'FinanceDataReader'), 'stock_count':len(ds['prices']), 'message': None}
        except HTTPException as e:
            return {'ready': False, 'dataset_id': None, 'financial_reports': 0, 'message': e.detail}

    def quote(self, symbol, day, year):
        ds = self.dataset(year)
        days, series = ds['prices'][symbol]
        i = bisect.bisect_right(days, day) - 1
        if i < 0:
            raise HTTPException(503, '게임 시작 전 기준 가격이 없어요.')
        row = series[i]
        prev = series[i - 1]['value'] if i > 0 else row['value']
        calendar_index = bisect.bisect_right(ds['calendar'], day) - 1
        if calendar_index < 0:
            raise HTTPException(503, '게임 시작 전 거래일 정보가 없어요.')
        latest_market_day = ds['calendar'][calendar_index]
        liquidatable = row['date'] == latest_market_day and row['volume'] > 0
        stock = BY_SYMBOL[symbol]
        return {k: stock[k] for k in ('symbol', 'name', 'sector', 'color')} | {
            'price': row['value'], 'price_date': row['date'], 'change': round((row['value'] / prev - 1) * 100, 4) if row['date'] == day else 0,
            'tradable': row['date'] == day and row['volume'] > 0 and day in ds['calendar'],
            'liquidatable': liquidatable, 'source': 'historical', 'updated_at': day, 'per': None, 'pbr': None}

    def quotes(self, day, year):
        return {s: self.quote(s, day, year) for s in BY_SYMBOL}

    def chart(self, symbol, day, year):
        days, rows = self.dataset(year)['prices'][symbol]
        end = bisect.bisect_right(days, day)
        return {'source': 'historical', 'points': [{'date': p['date'], 'value': p['value']} for p in rows[max(0, end - 120):end]]}

    def financials(self, symbol, day, year):
        reports = self.dataset(year)['financials'].get(symbol, [])
        # Receipt numbers must match the exact source rows, including correction dates.
        available = [r for r in reports if r['published_at'] <= day and r['period_end'] <= day
                     and all(x.get('rcept_no') == r['receipt'] for x in r['rows'])]
        available.sort(key=lambda r: (r['period_end'], r['published_at'], r['receipt']))
        report = available[-1] if available else None
        return {'source': 'opendart' if report else 'unavailable', 'as_of': day, 'report': report,
                'available_reports': [{k: r[k] for k in ('title', 'published_at', 'period_end', 'receipt')} for r in available],
                'message': None if report else '이 날짜까지 공개된 재무제표가 준비되지 않았어요. 미래 자료나 예시 수치로 대체하지 않아요.'}


market = HistoricalMarket()
