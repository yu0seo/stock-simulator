"""Curated universe; sample financials are educational fixtures, never live data."""
STOCKS = [
    dict(symbol='005930', name='삼성전자', sector='반도체', corp='00126380', price=72800, change=1.68, per=13.2, pbr=1.15, roe=8.7, revenue=300.9, profit=32.7, equity=391.7, debt=27.9, color='#2057ad'),
    dict(symbol='000660', name='SK하이닉스', sector='반도체', corp='00164779', price=186500, change=2.75, per=9.8, pbr=1.8, roe=18.4, revenue=66.2, profit=23.5, equity=75.8, debt=45.2, color='#e66833'),
    dict(symbol='035420', name='NAVER', sector='플랫폼', corp='00266961', price=214000, change=-0.93, per=19.4, pbr=1.3, roe=6.7, revenue=10.7, profit=1.9, equity=24.2, debt=37.1, color='#03a66a'),
    dict(symbol='005380', name='현대차', sector='자동차', corp='00164742', price=237000, change=0.85, per=5.4, pbr=0.58, roe=10.7, revenue=175.2, profit=14.2, equity=107.1, debt=181.5, color='#234a72'),
    dict(symbol='035720', name='카카오', sector='플랫폼', corp='00258801', price=42800, change=-1.38, per=34.1, pbr=1.5, roe=4.4, revenue=7.8, profit=0.5, equity=12.0, debt=62.0, color='#d7b108'),
    dict(symbol='051910', name='LG화학', sector='화학', corp='00356361', price=284000, change=1.25, per=26.4, pbr=0.82, roe=3.1, revenue=48.9, profit=0.9, equity=46.3, debt=93.0, color='#ae2559'),
    dict(symbol='105560', name='KB금융', sector='금융', corp='00688996', price=89200, change=0.56, per=6.7, pbr=0.52, roe=7.8, revenue=69.2, profit=6.1, equity=60.0, debt=1200.0, color='#8a7045'),
    dict(symbol='068270', name='셀트리온', sector='바이오', corp='00413046', price=181300, change=-0.44, per=48.5, pbr=2.1, roe=4.3, revenue=3.6, profit=0.5, equity=19.2, debt=25.2, color='#279783'),
]
BY_SYMBOL = {s['symbol']: s for s in STOCKS}
DIFFICULTIES = {
    'easy': dict(label='차근차근', loan=10_000_000, rate=0.04),
    'normal': dict(label='아슬아슬', loan=30_000_000, rate=0.09),
    'hard': dict(label='벼랑 끝', loan=50_000_000, rate=0.18),
}
LESSONS = [
    dict(id='per', title='PER, 이 회사의 가격표 읽기', category='기업 가치', minutes=3, reward=50000, text='PER은 주가를 주당순이익으로 나눈 값이에요. 같은 이익을 내는 회사라도 주가가 높으면 PER이 높아져요. 성장 기대, 일회성 이익, 업종 차이를 함께 살펴야 해요. 적자 기업에는 일반적인 PER 비교가 적절하지 않아요.', question='PER이 낮은 기업은 언제나 좋은 투자일까요?', options=['무조건 저평가된 기업이다', '업종과 성장성, 이익의 질을 함께 봐야 한다', '주가가 반드시 오른다'], answer=1, explanation='낮은 PER은 성장 둔화나 일시적인 이익 증가 때문일 수도 있어요. 숫자 하나로 투자를 결정하지 마세요.'),
    dict(id='pbr', title='PBR, 자산과 주가의 거리', category='기업 가치', minutes=3, reward=50000, text='PBR은 주가를 주당순자산으로 나눈 값이에요. 1배 미만이면 장부상 순자산보다 시가총액이 작다는 뜻이에요. 장부가치가 실제 매각가치를 보장하지 않고, 무형자산 비중에 따라서도 해석이 달라져요.', question='PBR이 1배 미만이라는 뜻은?', options=['장부상 순자산보다 시장 평가가 낮다', '원금이 보장된다', '부채가 전혀 없다'], answer=0, explanation='장부가치와 시장의 평가는 다를 수 있어요. 자산의 질과 수익성을 함께 확인하세요.'),
    dict(id='roe', title='ROE, 맡긴 돈을 얼마나 잘 쓸까?', category='수익성', minutes=4, reward=70000, text='ROE는 당기순이익을 자기자본으로 나눈 비율이에요. 자기자본을 활용해 이익을 내는 능력을 보여줘요. 부채를 늘려 자기자본 비중이 줄어도 ROE가 높아질 수 있으므로 부채비율도 확인해요.', question='높은 ROE를 볼 때 함께 살펴볼 지표는?', options=['회사 로고 색상', '부채비율과 이익의 지속성', '종목명의 길이'], answer=1, explanation='차입금 증가로 ROE가 높아질 수도 있어요. 수익성과 재무 안정성을 함께 살펴요.'),
    dict(id='debt', title='수익은 불확실해도, 이자는 확실해요', category='위험 관리', minutes=4, reward=100000, text='대출 이자는 주가가 오르든 내리든 쌓여요. 자기자본 1천만 원에 대출 1천만 원으로 2천만 원을 투자했을 때 10% 하락하면 손실 2백만 원은 자기자본의 20%예요. 여기에 이자도 부담해야 해요.', question='자기자본 1천만 원 + 대출 1천만 원으로 투자한 자산이 10% 하락하면 자기자본 손실률은? (이자 제외)', options=['10%', '20%', '5%'], answer=1, explanation='2천만 원의 10%인 2백만 원을 잃으면, 자기자본 1천만 원 기준 손실률은 20%예요.'),
]
