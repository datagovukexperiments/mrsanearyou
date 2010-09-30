import hashlib
import os

from google.appengine.api import memcache
from google.appengine.ext.webapp import template
from django.utils import simplejson 

import yql
import simplegeo

from simplegeo import Client, Record, APIError


MY_OAUTH_KEY = 'MYSEjzRKpyYBhSsZjse49PQJuHJmhYkn'
MY_OAUTH_SECRET = 'VH2JEDPGVYHJJehfPu2vmyWmhhFZz25d'


def chunker(seq, size):
    return (seq[pos:pos + size] for pos in xrange(0, len(seq), size))



def simple_geo_add(item, layer):
	client = Client(MY_OAUTH_KEY, MY_OAUTH_SECRET)
	records = []
	record = Record(
		layer=layer,
		id=str(item['key']),
		lat=item['lat'],
		lon=item['lon'],
		name=item['name']
    )                
	client.add_record(record)


def simple_geo_get(lat, lon, layer, limit, radius):
	keyhash = hashlib.md5(str(lat)+str(lon)+str(layer)+str(limit)+str(radius)).hexdigest()
	results = memcache.get(keyhash)
	if not results:
		try:
			client = Client(MY_OAUTH_KEY, MY_OAUTH_SECRET)
			results = client.get_nearby(layer, lat, lon, limit=limit, radius=radius)
			if results:
				memcache.set(keyhash, results, 3600)
		except:
			results = False
	return results


def do_yql(query):
	y = yql.Public()
	result = y.execute(query)
	return result


def get_lat_lon(place):
	place = place.strip()
	keyhash = hashlib.md5(place).hexdigest()
	lat = False
	lon = False
	name = False
	country = False
	placeset = memcache.get(keyhash)
	if not placeset:
		query = "select centroid, name, country from geo.places where text='%s'" % place
		try:
			placeset = do_yql(query)['query']['results']['place'][0]
		except:
			try:
				placeset = do_yql(query)['query']['results']['place']
			except:
				placeset = False
		if placeset:
			memcache.set(keyhash, placeset, 86400)
	if placeset:
		try:
			name = placeset['name']
		except:
			name = False
		try:
			country = placeset['country']['content']
		except:
			country = False
		try:
			latlon = placeset['centroid']['latitude'] + "," + placeset['centroid']['longitude']
			lat = float(latlon.split(",")[0])
			lon = float(latlon.split(",")[1])
		except:
			lat = False
			lon = False
	return lat, lon, name, country, placeset


def render_template(self, end_point, template_values):
	path = os.path.join(os.path.dirname(__file__), "templates/" + end_point)
	response = template.render(path, template_values)
	self.response.out.write(response)


def month_to_monthname(month):
	monthnames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
	month = int(month) - 1
	if month < 12:
		return monthnames[month]
	else:
		return False


def get_color(factor, value, r, g, b):
	modifier = 200 - (2 * value)
	hexcolor = '#%02x%02x%02x' % ((r + modifier), (g + modifier), (b + modifier))
	return hexcolor
