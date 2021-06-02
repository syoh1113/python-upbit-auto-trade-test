# 현재는 안쓰는 코드들을 모아놓은 파일, 추후 필요할 경우 해당 코드를 다듬어서 사용할 예정

# 각 종목들의 시/고/저/종가를 입력받아서 DB에 저장하는 함수
# 이후 사용할 경우, 비동기 함수로 구현한 뒤에 db 태스크를 통해 실행할 필요가 있음
def save_to_test_db(code, data):
    conn = sqlite3.connect("db/coinDB.db")
    cur = conn.cursor()
    conn.execute(
        '''
            CREATE TABLE if not exists tmp_test
                (market TEXT, date_time TEXT, o REAL, h REAL, l REAL, t REAL, unique(market, date_time))
        '''
    )
    conn.commit()

    o, h, l, c = data['ohlc']
    conn.execute(f'''
            insert or replace into tmp_test(market, date_time, o, h, l, t) values(?, ?, ?, ?, ?, ?)
        ''', (code, data['datetime'], o, h, l, c))
    conn.commit()


# db 내 두 테이블의 종목별 분봉 종가가 일치하는지 확인하는 테스트 함수
# 첫번째 테이블은 REST API 로 추후에 한번에 불러온 종목별 종가를 가지고 있음
# 두번째 테이블은 웹소켓을 이용하여 실시간으로 불러온 종목별 종가를 가지고 있음
# 만약 두 테이블을 비교하여 종목별 종가 데이터가 일치한다면, REST API 필요없이 실시간으로 종목별 분봉 종가를 가지고 올 수 있음을 의미한다
# 현재 테스트 한 결과, 웹소켓으로 종목별(약 118개 종목) 현재가를 불러올 경우에는 종가가 일치하지 않는 경우가 있음.
# 1. 웹소켓에 등록한 종목이 너무 많거나, 2. 현재가 말고 체결가를 불러와야 정확한 종가를 가져오는 건지 추가적인 확인이 필요하다.
async def test_real_data():
    async with aiosqlite.connect("db/coinDB.db") as db:
        # 현재 코드들을 가져온다.
        market_list = []
        async with db.execute("SELECT market FROM market_table WHERE market LIKE 'KRW-%'") as cursor:
            async for row in cursor:
                market_list.append(row[0])

        for market in market_list:
            # tmp 테이블로부터 현재 코드들의 date_time, ohlc 를 가져온다.
            new_data = {}
            async with db.execute(
                    f"SELECT date_time, o, h, l, t "
                    f"FROM tmp_test WHERE market = '{market}' ORDER BY date_time") as cursor:
                async for row in cursor:
                    date_time, o, h, l, c = row
                    new_data[date_time] = [o, h, l, c]

            # old_{code} 테이블로부터 date_time, ohlc 를 가져온다.
            new_data_start_time = min(new_data.keys())
            start_time = new_data_start_time[
                         0:4] + "-" + new_data_start_time[
                                      4:6] + "-" + new_data_start_time[
                                                   6:8] + "T" + new_data_start_time[
                                                                9:11] + ":" + new_data_start_time[
                                                                              11:13] + ":" + "00"
            old_data = []
            market_table_name = market.replace("-", "_")
            async with db.execute(
                    f"SELECT candle_date_time_utc, opening_price, high_price, low_price, trade_price "
                    f"FROM 'old_{market_table_name}' "
                    f"WHERE candle_date_time_utc >= '{start_time}' order by candle_date_time_utc") as cursor:
                async for row in cursor:
                    date_time, o, h, l, c = row
                    date_time = date_time[0:4] + date_time[5:7] + date_time[8:10] + "-" + date_time[11:13] + date_time[
                                                                                                             14:16]
                    old_data.append({'date_time': date_time, 'ohlc': [o, h, l, c]})

            # 두 테이블로부터 가져온 데이터를 비교한다.
            for d1 in old_data:
                dt1 = d1['date_time']

                if dt1 < '20210527-1800':
                    continue

                o1, h1, l1, c1 = d1['ohlc']

                if dt1 not in new_data.keys():
                    continue

                o2, h2, l2, c2 = new_data[dt1]
                if o1 != o2 or h1 != h2 or l1 != l2 or c1 != c2:
                    pass
