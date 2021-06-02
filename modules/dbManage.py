import math
import sys

import datetime

import aiosqlite


# 참고: https://pypi.org/project/aiosqlite/
async def db_manage(queue_dict, to_db_manage_id, with_upbit_api_manage_id, db_path):
    to_upbit_api_manage_id, from_upbit_api_manage_id = with_upbit_api_manage_id
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                    CREATE TABLE if not exists update_date_table
                    (id TEXT PRIMARY KEY, min_date TEXT, max_date TEXT)
                """
            )
            await db.commit()

            await db.execute(
                """
                    insert into update_date_table(id, min_date, max_date) select 'market_code','0','0'
                    where not exists (select * from update_date_table where id = 'market_code')
                """
            )
            await db.commit()

            async with db.execute(""" select min_date from update_date_table where id = 'market_code' """) as cursor:
                row = await cursor.fetchall()
                row = row[0]

                today = str(datetime.date.today())
                if str(row[0]) != today:
                    await db.execute(
                        """
                            CREATE TABLE if not exists market_table
                            (market TEXT PRIMARY KEY, korean_name TEXT, english_name TEXT)
                        """
                    )
                    await db.commit()

                    # 시장코드 요청
                    queue_dict[to_upbit_api_manage_id].put_nowait({
                        'code': '시장코드조회',
                        'response_id': from_upbit_api_manage_id
                    })
                    data = await queue_dict[from_upbit_api_manage_id].get()

                    await db.execute('delete from market_table')
                    market_list = data['시장코드목록']
                    for r in market_list:
                        market = r['market']
                        kr = r['korean_name']
                        en = r['english_name']
                        await db.execute(
                            'insert or replace into market_table(market, korean_name, english_name) values (?, ?, ?)',
                            (market, kr, en))
                    await db.execute(f'''update update_date_table 
                        set min_date = '{str(today)}', max_date = '{str(today)}' where id = 'market_code' ''')
                    await db.commit()

            await db.execute(
                """
                    CREATE TABLE if not exists real_data_table
                    (ty TEXT, cd text, td text, ttm text, sid integer, tp real, tv real, tms integer, 
                    tas real, tbs real, obu text, unique(ty, cd, td, tms))
                """
            )
            await db.commit()

            while True:
                data = await queue_dict[to_db_manage_id].get()

                code = data['code']
                response_id = data['response_id']

                if code == '시장코드조회':
                    result = []
                    async with db.execute('select market from market_table') as cursor:
                        async for row in cursor:
                            result.append(row)
                    queue_dict[response_id].put_nowait({
                        'code': code,
                        '시장코드목록': result
                    })

                elif code == 'save_db':
                    cd, ty, td, tms = data['cd'], data['ty'], data['td'], data['tms']
                    if ty == 'trade':
                        ttm, sid, tp, tv = data['ttm'], data['sid'], data['tp'], data['tv']
                        await db.execute(
                            """
                                insert or replace into real_data_table(ty, cd, td, ttm, sid, tp, tv, tms)
                                values (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (ty, cd, td, ttm, sid, tp, tv, tms))
                        await db.commit()
                    elif ty == 'orderbook':
                        tas, tbs, obu = data['tas'], data['tbs'], data['obu']
                        await db.execute(
                            """
                                insert or replace into real_data_table(ty, cd, td, tas, tbs, obu, tms)
                                values (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (ty, cd, td, tas, tbs, str(obu), tms)
                        )
                        await db.commit()

                elif code == 'update_date_table 갱신시간 요청':
                    market = data['market']

                    table_name = 'old_' + market

                    # 값이 없으면 초기값 넣기
                    await db.execute(
                        f"""
                            insert into update_date_table(id, min_date, max_date) select '{table_name}','0','0'
                            where not exists (select * from update_date_table where id = '{table_name}')
                        """
                    )
                    await db.commit()

                    async with db.execute(f""" select min_date, max_date 
                            from update_date_table where id = '{table_name}' """) as cursor:
                        row = await cursor.fetchall()
                        row = row[0]

                        queue_dict[response_id].put_nowait({
                            'code': code,
                            'min_date': row[0],
                            'max_date': row[1]
                        })

                elif code == '과거분봉데이터저장':
                    market, min_date, max_date, responses = \
                        data['market'], data['min_date'], data['max_date'], data['data']
                    table_name = 'old_' + market.replace('-', '_')

                    # 값이 없으면 테이블부터 생성
                    await db.execute(
                        f'''
                            CREATE TABLE if not exists {table_name}(candle_date_time_utc TEXT, 
                            candle_date_time_kst TEXT PRIMARY KEY, 
                            opening_price real, high_price real, low_price real, trade_price real,
                            timestamp integer, candle_acc_trade_price real, candle_acc_trade_volume real, unit integer)
                        '''
                    )
                    await db.commit()

                    for i in range(1, len(responses)):
                        res = responses[i]
                        await db.execute(
                            f'insert or replace into {table_name} values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (res['candle_date_time_utc'], res['candle_date_time_kst'],
                             res['opening_price'], res['high_price'], res['low_price'], res['trade_price'],
                             res['timestamp'], res['candle_acc_trade_price'], res['candle_acc_trade_volume'],
                             res['unit'])
                        )

                    db_format_time = "%Y-%m-%d %H:%M"
                    upbit_format_time = '%Y-%m-%dT%H:%M:%S'

                    if len(responses) > 0:
                        max_time_upbit = datetime.datetime.strptime(
                            responses[1]['candle_date_time_kst'], upbit_format_time
                        )
                        min_time_upbit \
                            = datetime.datetime.strptime(responses[-1]['candle_date_time_kst'], upbit_format_time)
                        if max_date == '0' or datetime.datetime.strptime(max_date, db_format_time) < max_time_upbit:
                            max_date = datetime.datetime.strftime(max_time_upbit, db_format_time)
                            await db.execute(
                                f"update update_date_table set max_date = '{max_date}' where id = 'old_{market}'")
                        if min_date != '-1' and \
                                (min_date == '0' or
                                 datetime.datetime.strptime(min_date, db_format_time) > max_time_upbit):
                            min_date = datetime.datetime.strftime(min_time_upbit, db_format_time)
                            await db.execute(
                                f'''update update_date_table set min_date = '{min_date}' where id = 'old_{market}' ''')

                    if len(responses) < 200:
                        await db.execute(f'''update update_date_table set min_date = '-1' where id = 'old_{market}' ''')
                        min_date = '-1'

                    await db.commit()

                    queue_dict[response_id].put_nowait({'code': code, 'min_date': min_date, 'max_date': max_date})

                elif code == '총분봉데이터요청':
                    market = data['market']
                    result = []
                    async with db.execute(f"select * from 'old_{market.replace('-', '_')}' "
                                          f"order by candle_date_time_kst") as cursor:
                        async for row in cursor:
                            result.append(row)
                    queue_dict[response_id].put_nowait({
                        'code': code,
                        '총분봉데이터': result
                    })

                elif code == '시뮬레이션보조지표저장요청':
                    market = data['market']
                    raw_data = data['data']
                    results = data['results']
                    results = results['results']

                    for k in results.keys():
                        result_k = results[k]

                        if len(raw_data) != len(result_k):
                            print("길이 불일치")
                        else:
                            table_name = 'old_' + market.replace("-", "_")

                            column_found = False
                            if k == 'RSI':
                                async with db.execute(f"pragma table_info('{table_name}')") as cursor:
                                    async for row in cursor:
                                        if row[1] == 'rsi':
                                            column_found = True
                                            break
                                if not column_found:
                                    await db.execute(f"alter table '{table_name}' add column rsi real")
                                    await db.commit()
                                for i in range(len(result_k)):
                                    time_kst, rsi = raw_data[i][1], result_k[i]
                                    if math.isnan(result_k[i]):
                                        continue
                                    await db.execute(f"update '{table_name}' set rsi = {rsi} "
                                                     f"where candle_date_time_kst = '{time_kst}'")
                                await db.commit()

                    queue_dict[response_id].put_nowait({'code': code})

    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        print(exc_tb.tb_lineno)
        print(e)
        pass
