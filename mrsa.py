import csv
import math
import datetime

from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.api import urlfetch
from google.appengine.ext import db
from google.appengine.api.labs import taskqueue
from google.appengine.api import memcache


import helpers


class Trust(db.Model):
	code = db.StringProperty()
	category = db.StringProperty()
	type = db.StringProperty()
	name = db.StringProperty()
	address_1 = db.StringProperty()
	address_2 = db.StringProperty()
	address_3 = db.StringProperty()
	town = db.StringProperty()
	county = db.StringProperty()
	postcode = db.StringProperty()
	lat = db.StringProperty()
	lon = db.StringProperty()
	recordlist = db.StringListProperty()
	total = db.IntegerProperty(default=0)
	count = db.IntegerProperty(default=0)
	average = db.FloatProperty(default=0.0)


class Record(db.Model):
	trust = db.ReferenceProperty(Trust)
	date = db.DateTimeProperty()
	datestring = db.StringProperty()
	value = db.IntegerProperty()


MONTHLIST = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
NHS_LAYER = 'uknhstrusts'


def convert_date(theirdate):
	dateelements = theirdate.split("_")
	year = int(dateelements[1])
	day = 1
	i = 0
	for monthname in MONTHLIST:
		i += 1
		if dateelements[0] == monthname:
			month = i 
	return day, month, year


class ImportHandler(webapp.RequestHandler):
	def get(self):
		if self.request.get("page"):
			page = int(self.request.get("page"))
		else:
			page = 1
		trusts = csv.reader(open('datasources/mrsatrusts.csv'), delimiter=',', quotechar='\"')		
		i = 0
		t = {
		 "records": []
		}
		for trust in trusts:
			if i > 0:
				if i == page:
					k = 0
					for item in trust:
						if len(trustlabels[k]) > 0:
							hasmoredata = True
							label = str(trustlabels[k].lower().replace(" ", "_"))
							if k < 5 or k > 17:
								if not label in t:
									t[label] = item.title()
								if label in ["postcode", "trust_code", "trust_category", "trust_type"]:
									t[label] = item
							else:
								day, month, year = convert_date(label)
								datestring = label
								date = datetime.datetime(year, month, day)
								t["records"].append({
										"value":int(item),
										"datestring":datestring,
										"date":date,
								}) 
						k += 1
			else:
				trustlabels = trust
			i += 1
		self.response.out.write(t)
		if "trust_code" in str(t):
			tkey = t["trust_code"].lower()
			trust = Trust.get_or_insert(tkey, code=t["trust_code"], category=t["trust_category"], type=t["trust_type"], name=t["trust_name"], address_1=t["address_1"], address_2=t["address_2"], address_3=t["address_3"], town=t["town"], county=t["county"], postcode=t["postcode"])
			for record in t["records"]:
				rkey = t["trust_code"].lower() + "_" + record["datestring"]
				record = Record.get_or_insert(rkey, trust=trust, date=record["date"], datestring=record["datestring"], value=record["value"])
				if rkey not in trust.recordlist:
					trust.recordlist.append(rkey)
					trust.total += record.value
					trust.count += 1
					trust.average = float(trust.total) / float(trust.count)
			trust.put()
			if hasmoredata:
				taskqueue.add(url="/mrsanearyou/importer", params={"page": str(page + 1)}, method='GET')
			taskqueue.add(url="/mrsanearyou/geoimporter", params={"keyname": tkey}, method='GET')

		
class GeoImportHandler(webapp.RequestHandler):
	def get(self):
		keyname = self.request.get("keyname")
		trust = Trust.get_by_key_name(keyname)
		if trust:
			lat, lon, name, country, placeset = helpers.get_lat_lon(trust.postcode)
			if lat:
				self.response.out.write(lat)
				self.response.out.write(lon)
				item = {
					"lat":lat,
					"lon":lon,
					"name":trust.name,
					"key":keyname
					}
				helpers.simple_geo_add(item, NHS_LAYER)
				trust.lat = str(lat)
				trust.lon = str(lon)
				trust.put()


def get_label_color(average):
	bestlist, count = build_leaguetable("best")
	best = bestlist[0]["average"]
	worst = bestlist[count - 1]["average"]
	labelvalue = round((worst - average)/worst, 2)
	if labelvalue > 0.95:
		color = "ffffff"
	elif labelvalue > 0.9:
		color = "eecccc"
	elif labelvalue > 0.8:
		color = "cc9999"
	elif labelvalue > 0.7:
		color = "bb6666"
	elif labelvalue > 0.4:
		color = "aa3333"
	else:
		color = "990000"
	return color, labelvalue


def get_trustset(self, keyset, results):
	trusts = Trust.get_by_key_name(keyset)
	trustset = []
	i = 0
	for trust in trusts:
		labelcolor, labelvalue = get_label_color(trust.average)
		trustrecord = {
							"trust_code": trust.key().name(),
							"name": trust.name,
							"town": trust.town,
							"county": trust.county,
							"postcode": trust.postcode,
							"average": round(trust.average, 2),
							"lat": trust.lat,
							"lon": trust.lon,
							"labelvalue": labelvalue,
							"labelcolor": labelcolor,
							"best": get_leaguetable_position(self, trust.key().name(), "best"),
							"worst": get_leaguetable_position(self, trust.key().name(), "worst"),
							"distance": round((float(results[i]["distance"])*0.621371192)/1000, 2)
						}
		trustset.append(trustrecord)
		i+=1
	return trustset, i


def get_results(lat, lon):
	results = helpers.simple_geo_get(lat, lon, NHS_LAYER, 9, 30)["features"]
	if results:
		keyset = []
		i = 0
		for result in results:
			keyset.append(result["id"])
			i+=1
	else:
		keyset = False
	return results, keyset


def get_leaguetable_position(self, keyname, direction):
	trustlist, count = build_leaguetable(direction)
	position = 0
	for trustitem in trustlist:
		if trustitem["keyname"] == keyname:
			position = trustitem["position"]
	return position


def build_leaguetable(direction):
	trustlist = memcache.get(direction)
	position = 0
	if not trustlist:
		if direction == "best":
			trusts = Trust.all().order("average")
		else:
			trusts = Trust.all().order("-average")
		i = 1
		trustlist = []
		for trust in trusts:
			trustlist.append({
				"keyname": trust.key().name(),
				"position": i,
				"average": trust.average
			})
			i += 1
		memcache.set(direction, trustlist, 86400)
	return trustlist, len(trustlist)


class MainViewHandler(webapp.RequestHandler):
	def get(self):
		self.post()
	def post(self):
		lat = False
		lon = False
		name = False
		country = False
		results = False
		trustset = False
		count = 0
		totalcount = 0
		if self.request.get("q"):
			q = self.request.get("q")
		else:
			q = ""
		if len(q) > 0:
			lat, lon, name, country, placeset = helpers.get_lat_lon(q + " UK")
			if lat:
				results, keyset = get_results(lat, lon)
				if results:
					trustlist, totalcount = build_leaguetable("best")
					trustset, count = get_trustset(self, keyset, results)
				else:
					trustset = False
					count = 0
		if not name:
			name = q
		template_values = {
			"q": q,
			"lat": lat,
			"lon": lon,
			"name": name,
			"country": country,
			"trustset": trustset,
			"count": count,
			"totalcount": totalcount
		}
		helpers.render_template(self, "mrsa/home.html", template_values)


class GraphHandler(webapp.RequestHandler):
	def get(self, graphtype, keyname):
		img = memcache.get(graphtype + "_" + keyname)
		if not img:
			trust = Trust.get_by_key_name(keyname)
			records = Record.get_by_key_name(trust.recordlist)
			recordstring = ""
			for record in records:
				recordstring += str(record.value) + ","
			if len(recordstring) > 0:
				recordstring = recordstring[0: len(recordstring) - 1]
			if graphtype == "top":
				background = "ddeeff"
			elif graphtype == "results":
				background = "bbdd99"
			charturl = "http://chart.apis.google.com/chart?cht=bvs&chs=600x20&chd=t:"+ recordstring +"&chco=ffffff&chbh=20&chds=0,10&chf=bg,s,"+ background +"&chbh=10,5"
			result = urlfetch.fetch(charturl)
			if result.status_code == 200:
  				img = result.content
				if img:
					memcache.set(graphtype + "_" + keyname, img, 86400)
		self.response.headers['Content-Type'] = 'image/png'
		self.response.out.write(img)


class MapHandler(webapp.RequestHandler):
	def get(self, keyname):
		img = memcache.get("map_" + keyname)
		if not img:
			trust = Trust.get_by_key_name(keyname)
			mapurl = "http://maps.google.com/maps/api/staticmap?size=100x100&maptype=roadmap&markers=size:large|color:white|"+ trust.lat +","+ trust.lon +"&zoom=14&sensor=false"
			result = urlfetch.fetch(mapurl)
			if result.status_code == 200:
  				img = result.content
				if img:
					memcache.set("map_" + keyname, img, 86400)
		self.response.headers['Content-Type'] = 'image/png'
		self.response.out.write(img)
		
			