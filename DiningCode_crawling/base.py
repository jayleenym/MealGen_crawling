from selenium import webdriver
import selenium
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException,ElementClickInterceptedException

from bs4 import BeautifulSoup
from requests.compat import urlparse, urljoin
from requests.exceptions import HTTPError
from requests import Session
import requests
import pickle

import pandas as pd
import time
import datetime
from tqdm import tqdm
import re
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(os.getcwd())))

# db management libraries
import pymysql
from controller import MysqlController



options = webdriver.ChromeOptions()
# options.add_argument("--headless")
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

# Path
chromedriver_path = 'C://Users//user//Desktop//chromedriver'

class DiningCode():
    def __init__(self, file = None):
        if not file:
            _id = input("input id(root) : ")
            _pw = input("input pw       : ")
            _db = input("databases      : ")
            connect_info = ("localhost", 3306, _id, _pw, _db)
        else:
            with open(os.path.join(sys.path[0], file), "r") as f:
                connect_info = list(map(lambda x: x.strip(), f.read().split(",")))
        self.controller = MysqlController(*connect_info)
        self.driver = webdriver.Chrome(executable_path = chromedriver_path, options = options)
        # 기본 설정
        self.one_name = ''
        self.one_id = ''
        self.one_url = ''
        # 주소지 받아오기
        self.controller.curs.execute('SELECT DISTINCT CONCAT(sido, " ", sigungu, " ",dong) as adr FROM Address;')
        self.ADR = ADR = [f[0].replace("(알수없음)", "").replace("세종특별자치시 세종특별자치시", "세종특별자치시") 
                          for f in self.controller.curs.fetchall() if (f[0] != None) and (f[0] != "세종특별자치시 세종특별자치시 (알수없음)")]

    def get_all_rtr(self, address : str):
       # 첫 window로 들어가기
        self.driver.switch_to.window(self.driver.window_handles[0])
        # 위치로 페이지 들어가기
        url = f'https://www.diningcode.com/list.php?query={address}'
        self.driver.get(url)

        # 더보기 클릭(최대 100개)
        while True:
            try:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                self.driver.find_element_by_css_selector('#div_list_more').click()
                time.sleep(1.5)
            except:
                break

        # 더보기 한 상태로 식당 리스트 가져오기 : 광고 제거 잘 되는지 검사?
        res_list = [res for res in self.driver.find_elements_by_css_selector('#div_list > li') if type(res.get_property('onmouseenter')) == dict] 
        return res_list

    
    def get_one_info(self, one):
        self.driver.switch_to.window(self.driver.window_handles[0])
        self.one_url = one.find_element_by_tag_name('a')
        self.one_id = re.findall('rid=(.*)', self.one_url.get_attribute('href'))[0]

        # 중복 체크
        self.controller.curs.execute(f"""SELECT count(*) FROM diningcode_restaurants
                                        WHERE rid = '{self.one_id}' 
                                        AND parking is not NULL;""")
        if self.controller.curs.fetchone()[0] >= 1: return
        
        # 클릭해서 open & driver 옮기기
        self.one_url.click()
        time.sleep(1)
        self.driver.switch_to.window(self.driver.window_handles[1])

        # 식당명 제대로 뜰 때까지
        while True:
            try:
                self.one_name = self.driver.find_element_by_css_selector('div.tit-point').text
                break
            except:
                time.sleep(1.5)
                self.driver.refresh()

        # 점수 없을수도
        try:
            one_grade = float(self.driver.find_element_by_css_selector('div.sns-grade strong').text.replace('점', ''))
        except:
            one_grade = 0.0
        
        # 사용자 평점 없을수도
        try:
            one_star = float(self.driver.find_element_by_css_selector('div.sns-grade span.point strong').text.replace('점', ''))
        except:
            one_star = 0.0

        # 카테고리 없을수도
        try:
            one_category = self.driver.find_element_by_css_selector('div.btxt').text.split('|')[1].strip()
        except:
            one_category = ''
        
        try:
            one_parking = int('주차' in self.driver.find_element_by_css_selector('ul.list li.char').text)
        except:
            one_parking = 0
        
        # 식당 정보 입력
        # 업데이트
        self.controller.curs.execute(f"""SELECT count(*) FROM diningcode_restaurants
                                        WHERE rid = '{self.one_id}';""")
        if self.controller.curs.fetchone()[0] >= 1: 
            self.controller.curs.execute(f"""
                UPDATE diningcode_restaurants 
                SET parking = '{one_parking}', updated_at = now()
                WHERE rid = '{self.one_id}';""")
            self.controller.conn.commit()
        else:
            self.controller.insert('diningcode_restaurants', {
                'updated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'rname': self.one_name,
                'rid': self.one_id, 
                'category': one_category,
                'grade' : one_grade,
                'star' : one_star,
                'favorite' : int(self.driver.find_element_by_css_selector('div.favor-pic-appra i').text),
                'address' : self.driver.find_element_by_css_selector('li.locat').text,
                'phone' : self.driver.find_element_by_css_selector('li.tel').text,
                'parking' : one_parking
            })

    
    def get_one_menus(self):
        # 안 열려 있으면 열기 
        if len(self.driver.window_handles) == 1: self.one_url.click()
        self.driver.switch_to.window(self.driver.window_handles[1])
        # 메뉴 더보기
        try:
            self.driver.find_element_by_css_selector('#div_detail div.menu-info a.more-btn').click()
        except:
            pass
        
        menu = [m.text.replace("'", '"') for m in self.driver.find_elements_by_css_selector('ul.list.Restaurant_MenuList li p.l-txt.Restaurant_MenuItem') if m.text != '']
        price = [p.text for p in self.driver.find_elements_by_css_selector('ul.list.Restaurant_MenuList li p.r-txt.Restaurant_MenuPrice') if p.text != '']
        
        if (len(menu) != 0) and (len(menu) == len(price)):
            for i in range(len(menu)):
                # 중복 체크
                self.controller.curs.execute(f"""SELECT count(*) 
                                        FROM diningcode_menu 
                                        WHERE rid = '{self.one_id}'
                                        AND menu = '{menu[i]}';""")
                if self.controller.curs.fetchone()[0] >= 1: continue
                
                self.controller.insert('diningcode_menu', line = {
                    'updated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'rname': self.one_name,
                    'rid': self.one_id,
                    'menu' : menu[i],
                    'price' : price[i]
                })

    
    def get_one_rvs(self):
        # 안 열려 있으면 열기 
        if len(self.driver.window_handles) == 1: self.one_url.click()
        self.driver.switch_to.window(self.driver.window_handles[1])
        # 더보기
        while True:
            try:
                self.driver.find_element_by_css_selector('#div_more_review').click()
                time.sleep(1.2)
            except: break
        
        # 리뷰 크롤링
        # reviewers = [re.findall('(.*) [(](.*)[)]', pr.text)[0] for pr in self.driver.find_elements_by_css_selector('p.person-grade span.btxt')]
        # review = [r.text.replace("'", '"') for r in self.driver.find_elements_by_css_selector('p.review_contents.btxt')]
        # date = [d.text for d in self.driver.find_elements_by_css_selector('span.star-date')]
        # star = [s for s in self.driver.find_elements_by_css_selector('i.star > i')]

        # if len(reviewers) != 0:
        #     for i in range(len(reviewers)):
        for one in self.driver.find_elements_by_css_selector('div.latter-graph'):
            # 리뷰어 아이디, 없을 수도 있음
            try:
                reviewer = re.findall('(.*) [(].*[)]', one.find_element_by_css_selector('p.person-grade span.btxt').text)[0]
            except:
                reviewer = ""
            
            try:
                info = re.findall('[(](.*)[)]', one.find_element_by_css_selector('p.person-grade span.btxt').text)[0]
            except:
                info = ""
            
            # 리뷰 내용; 숨김처리 예외
            try: review = one.find_element_by_css_selector('p.review_contents.btxt').text.replace("'", '"')
            except: review = ""
            # 리뷰 중복체크
            self.controller.curs.execute(f"""SELECT count(*) 
                                    FROM diningcode_reviews 
                                    WHERE rid = '{self.one_id}'
                                    AND review = '{review}';""")
            if self.controller.curs.fetchone()[0] >= 1: continue

            # 리뷰 날짜
            date = one.find_element_by_css_selector('span.star-date').text
            try:
                d = datetime.datetime.strptime(date, "%Y년 %m월 %d일") 
            except:
                if re.match('[0-9]+월 [0-9]+일', date): 
                    d = datetime.datetime.strptime("2021년 "+date, "%Y년 %m월 %d일")
                if re.match('[0-9]+일 전', date):
                    d = datetime.datetime.now() - datetime.timedelta(days = int(re.findall('([0-9]+)일 전', date)[0]))
                if re.match('[0-9]+시간 전', date):
                    d = datetime.datetime.now() - datetime.timedelta(hours = int(re.findall('([0-9]+)시간 전', date)[0]))
                if re.match('[0-9]+분 전', date):
                    d = datetime.datetime.now() - datetime.timedelta(minutes = int(re.findall('([0-9]+)분 전', date)[0]))
                
                if re.match("어제 [가-힇]+ [0-9]+시 [0-9]+분", date):
                    yesterday = datetime.datetime.now() - datetime.timedelta(days = 1)
                    hr = int(re.findall("([0-9]+)시", date)[0])
                    mt = int(re.findall("([0-9]+)분", date)[0])
                    if re.findall("([가-힇]+) [0-9]+시", date)[0] == '오후': hr += 12
                    d = datetime.datetime(yesterday.year, yesterday.month, yesterday.day, hr, mt)
                if re.match("오늘 [가-힇]+ [0-9]+시 [0-9]+분", date):
                    today = datetime.datetime.now()
                    hr = int(re.findall("([0-9]+)시", date)[0])
                    mt = int(re.findall("([0-9]+)분", date)[0])
                    if re.findall("([가-힇]+) [0-9]+시", date)[0] == '오후': hr += 12

                    d = datetime.datetime(today.year, today.month, today.day, hr, mt)
                    
            if type(d) == datetime.datetime:
                d = datetime.datetime.strftime(d, '%Y-%m-%d')
            else:
                d = datetime.datetime.strftime(datetime.datetime(1, 1, 1), '%Y-%m-%d')

            # 별점
            star = one.find_element_by_css_selector('i.star > i')

            # table에 입력
            self.controller.insert('diningcode_reviews', line = {
                'updated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'rname': self.driver.find_element_by_css_selector('div.tit-point').text,
                'rid': self.one_id,
                'reviewer' : reviewer,
                'reviewer_info' : info,
                'star' : int(re.findall('[0-9]+', star.get_attribute('style'))[0]) / 100 * 5 ,
                'review' : review,
                'date' : d
            })
