""" A depth traversal/search of internal wiki links from a beginning article.
"""
import requests
import logging
import os
import time
import json

from sqlalchemy import Column, Integer, String, Index
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


LOG_FILENAME = "debug.log"
logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG)

DEPTH = 3
TRAVERSAL_SPEED_S = 0.3

# shim to view progress in the console, can be removed later.
OUTPUT_COUNT = 0

TARGET_WIKI_URL = "https://en.wikipedia.org/w/api.php"

# easy to read header config section
headers = dict()
headers['user-agent'] = 'wGJF/0.0.1'


Base = declarative_base()

class Links(Base):
    """ 
    Timestamps are for cache management. Use unix epoch time.

    Wikipedia Title Limit is 256 characters: https://en.wikipedia.org/wiki/Wikipedia:Naming_conventions_(technical_restrictions)#Title_length

    256*5000=1,280,000
    """
    __tablename__ = 'links'

    id = Column(Integer, primary_key=True)
    page = Column(String(256), index=True)
    links = Column(String(1280000))
    timestamp = Column(Integer)
    depth = Column(Integer, default=-1)
    

PROJECT_ROOT = os.path.dirname(os.path.realpath(__file__))
DB_NAME = "links.sqlite"
DB_DIR = "database"
SQLITE_DB = 'sqlite:////' + os.path.join(PROJECT_ROOT, DB_DIR, DB_NAME)

engine = create_engine(SQLITE_DB)

Session = sessionmaker()
Session.configure(bind=engine)
session = Session()


def endpoint_initializer(title, pllimit='5000', prop='links', action='query', _format='json'):
    """ Set up an endpoint with some defaults and an article title.
    """

    # this formatting is a little easier on the eyes for simple settings dicts.
    endpoint = dict()
    endpoint['action'] = action
    endpoint['format'] = _format
    endpoint['titles'] = title
    endpoint['prop'] = prop
    endpoint['pllimit'] = pllimit

    return endpoint


def get_exit_links(url, headers, endpoint):
    """ Build the request, hit the URL specified in params, return the exit_links
    """
    r = requests.get(url, headers=headers, params=endpoint)

    exit_links = list()

    # munge exit links from the json response
    if r.status_code == 200:
        entry_info = r.json()
        for k, v in entry_info['query']['pages'].iteritems():
            if len(entry_info['query']['pages'].keys()) > 1:
                logging.debug("Why was more than one page returned in this query?")
            if 'links' in v:
                for link in v['links']:
                    if link['ns'] == 0:
                        exit_links.append(link['title'])
    else: 
        logging.debug("Request failed at: {}, error {}.".format(url, r.status_code))

    if len(exit_links) > 5000:
        logging.debug("More than 5000 titles at: {}, a longer handling script should be created.".format(url))

    return exit_links


def collect_routes(depth_counter, next_title, title_route=tuple()):
    """ Recursively collect links a certain depth from next_title

    Future goal: record two more pieces of data during traversal:
    1. does this page have a link to the TARGET_PAGE
    2. does an nth descendant of this page have a link to the target page?

    We can track the nth descendant by returning `True` up the stack if a page is found, otherwise
    returning false.
    We can track the current page by recording it in place.
    
    This process recommends we build a new database table for the TARGET_PAGE and
    link cached items to the page by foreign key.

    Then the results will be cached in a nice database and relevant descendants can be 
    fruitfully traversed and irrelevant descendants can be ignored.
    """

    # shim to view progress in console, can be removed later
    global OUTPUT_COUNT
    OUTPUT_COUNT += 1
    if not OUTPUT_COUNT % 1000:
        print(OUTPUT_COUNT)


    title_route += (next_title,)

    session.expunge_all()
    instance = session.query(Links).filter(Links.page == next_title).first()

    # don't do ANYTHING if we have already traversed at least depth_counter deep
    if instance:
        if depth_counter > instance.depth:
            exit_links = json.loads(instance.links)

            """
            # code to update cache if triggered, not currently used
            # to add this in, use endpoint_initializer and get_exit_links
            try:
                link_update = { timestamp : _timestamp, links : links }
                instance.update(link_update)
                session.commit()
            except:
                session.rollback()
            """
        else:
            # depth has already been traversed
            # this control structure needs unrolled
            return
            
    else:
        print("Traversing Route: {}".format(title_route))
        time.sleep(TRAVERSAL_SPEED_S)

        endpoint = endpoint_initializer(next_title)
        exit_links = get_exit_links(TARGET_WIKI_URL, headers, endpoint)

        # Set up the sqlalchemy object
        _page = next_title
        _links = json.dumps(exit_links)
        _timestamp = int(time.time())
        _linkdata = Links(page=_page, links=_links, timestamp=_timestamp)

        try:
            session.add(_linkdata)
            session.commit()
        except:
            session.rollback()

    # SIMPLE RESULTS: record routes that return to TARGET_TITLE.
    if TARGET_TITLE in exit_links:
        logging.debug("Return route found at depth {}: {}".format(depth_counter, title_route))

    if depth_counter > 0:
        for title in exit_links:
            # keep digging unless we hit TARGET_TITLE.
            if title != TARGET_TITLE:
                collect_routes((depth_counter-1), title, title_route)
    else:
        # base case, stop traversing
        pass

    ##
    ## Finally record the furthest depth you have traversed from this page.
    ##

    # find the instance if it is freshly made, or just use the one that already exists.
    if not instance:
        instance = session.query(Links).filter(Links.page == next_title).first()

    # if an instance exists (it may have failed out)
    # then store the traversal depth completed during recursive calls inside this function.
    # depth is initialized to -1 in the database, this depth is impossible.
    if instance:
        if depth_counter > instance.depth:
            try:
                instance.depth = depth_counter
                session.commit()
            except:
                # should probably record that this happened somewhere. this shouldn't happen.
                session.rollback()
    else:
        # instance must have failed out somehow, probably should record this and try again later
        pass

    return


if __name__ == "__main__":
    """
    The most powerful tool is currently results cacheing.

    The results we get inside the recursive function include any article
    that links back to the TARGET_TITLE and its depth from the ROOT_TITLE.

    This could be annotated somewhere, but this general tool is much
    more powerful than this special use.
    """
    # use care, underscores in the url need to be spaces in the title for the comparison to work.
    ROOT_TITLE = "Python (programming language)"
    TARGET_TITLE = ROOT_TITLE

    collect_routes(DEPTH, ROOT_TITLE)
