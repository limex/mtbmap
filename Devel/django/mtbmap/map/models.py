#!/usr/bin/python
# -*- coding: utf-8 -*-

# Global imports
from copy import deepcopy
from random import randint
import simplejson as json
from textwrap import wrap

# Django imports
from django.db import models
from django.contrib.gis.db import models as geomodels
from django.contrib.gis.geos import *

# Local imports
from map.mathfunctions import haversine
from map.updatemap import updatemap

SAC_SCALE_CHOICES = (
 (0, 'hiking'),
 (1, 'mountain_hiking'),
 (2, 'demanding_mountain_hiking'),
 (3, 'alpine_hiking'),
 (4, 'demanding_alpine_hiking'),
 (5, 'difficult_alpine_hiking'),
)

WEIGHTS = [1, 2, 3, 6, 12]
MAX_WEIGHT = max(WEIGHTS)
MIN_WEIGHT = min(WEIGHTS)
THRESHOLD = 2*max(WEIGHTS)

class Map(models.Model):
    name = models.CharField(max_length=200)
    attribution = models.CharField(max_length=400)
    url = models.CharField(max_length=400)
    last_update = models.DateField(null=True, blank=True)

    def __unicode__(self):
        return u"%s,%s" % (self.name, self.url)

    def as_dict(self):
        return {'name':self.name, 'url':self.url}
    
    def update_rendering_data(self, config_file):
        """
        Update data used for map rendering and timestamp.
        """
        date = updatemap(config_file)
        if date:
            self.last_update = date
            self.save()
        else:
            print 'An error occured'

class Way(geomodels.Model):
    class_id = models.BigIntegerField(null=True, blank=True)
    length = models.FloatField(null=True, blank=True)
    name = models.CharField(max_length=200)
    x1 = models.FloatField()
    y1 = models.FloatField()
    x2 = models.FloatField()
    y2 = models.FloatField()
    reverse_cost = models.FloatField(null=True, blank=True)
    osm_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    the_geom = geomodels.LineStringField()
    source = models.BigIntegerField(db_index=True)
    target = models.BigIntegerField(db_index=True)

    #cost attributes
    highway = models.TextField(null=True, blank=True)
    tracktype = models.IntegerField(null=True, blank=True)
    oneway = models.TextField(null=True, blank=True)
    access = models.TextField(null=True, blank=True)
    bicycle = models.TextField(null=True, blank=True)
    foot = models.TextField(null=True, blank=True)
    incline = models.TextField(null=True, blank=True)
    width = models.FloatField(null=True, blank=True)
    surface = models.TextField(null=True, blank=True)
    smoothness = models.TextField(null=True, blank=True)
    maxspeed = models.TextField(null=True, blank=True)
    osmc = models.IntegerField(null=True, blank=True)
    mtbscale = models.IntegerField(null=True, blank=True)
    mtbscaleuphill = models.IntegerField(null=True, blank=True)
    sac_scale = models.IntegerField(null=True, blank=True)
    network = models.TextField(null=True, blank=True)
    class_bicycle = models.IntegerField(null=True, blank=True)
    class_mtb = models.IntegerField(null=True, blank=True)
    class_mtb_technical = models.IntegerField(null=True, blank=True)

    objects = geomodels.GeoManager()

    def __unicode__(self):
        return u"Way(%s, %s)" % (self.osm_id, self.highway)

    def point_intersection(self, point):
        '''
        Project Point(latlon) on the way.
        return tuple (projected point on the way, index of the previous way coordinate)
        '''
        segment, index = self._nearest_segment(point)
        a = Point(segment[0])
        b = Point(segment[-1])
        ux = b.x - a.x
        uy = b.y - a.y
        t = ((point.x - a.x)*ux + (point.y - a.y)*uy)/(ux**2 + uy**2)
        if t<=0:
            ret = a
        elif t>=1:
            ret = b
        else:
            x = a.x + ux*t
            y = a.y + uy*t
            ret = Point(x, y)
        return ret, index

    def _nearest_segment(self, point):
        '''
        Find nearest segment of Way to the given point.
        return tuple (linestring, index of starting point of segment)
        '''
        distances = [ LineString(self.the_geom[i], self.the_geom[i+1]).distance(point) for i in range(len(self.the_geom)-1)]
        index = distances.index(min(distances))
        return LineString(self.the_geom[index], self.the_geom[index+1]), index

    def lines_to_endpoints(self, point):
        '''
        Project point attribute on this Way, find out geometries of this Way
        splitted in intersection point.
        return tuple (line to source, line to target)
        '''
        split_point, index = self.point_intersection(point)
        to_source = LineString(self.the_geom[:index+1] + [split_point])
        to_target = LineString([split_point] + self.the_geom[index+1:])
        return (to_source, to_target)

    def point_to_point(self, start, end):
        '''
        Project two points(latlon) on the way, find line between the projections.
        Used when both points have this Way as nearest_way.
        return Way with correctly computed geometry and length
        '''
        start_split, start_index = self.point_intersection(start)
        end_split, end_index = self.point_intersection(end)
        if start_index<end_index:
            geometry = LineString([start_split] + self.the_geom[start_index+1:end_index+1] + [end_split])
        else:
            geometry = LineString([end_split] + self.the_geom[end_index+1:start_index+1] + [start_split])
        way = deepcopy(self)
        way.id = None
        way.the_geom = geometry
        way.length = way.compute_length()
        print way.length
        return way

    def split(self, point):
        '''
        Split Way in the projected point, save both parts to the database.
        Way source or target are random negative values (new vertice).
        return tuple(way to source, way to target, new routing vertice ID)
        '''
        to_source = deepcopy(self)
        to_source.id = None
        to_target = deepcopy(self)
        to_target.id = None
        to_source.the_geom, to_target.the_geom = self.lines_to_endpoints(point)
        split_point, index = self.point_intersection(point)
        vertice = randint(-100000, -100)
        to_source.target = vertice
        to_target.source = vertice
        to_source.x2 = split_point.x
        to_source.y2 = split_point.y
        to_target.x1 = split_point.x
        to_target.y1 = split_point.y
        to_source.osm_target = None
        to_target.osm_source = None
        to_source.save()
        to_target.save()
        geom = LineString(point, split_point)
        geom.set_srid(4326)
        way_to_intersection = Way(the_geom=geom)
        way_to_intersection.length = way_to_intersection.compute_length()

        # workaround to compute correct lengths
        to_source.length = Way.objects.length().get(pk=to_source.id).length.km
        to_target.length = Way.objects.length().get(pk=to_target.id).length.km
        if self.length != self.reverse_cost:
            to_source.reverse_cost = self.reverse_cost
            to_target.reverse_cost = self.reverse_cost
        else:
            to_source.reverse_cost = to_source.length
            to_target.reverse_cost = to_target.length
        to_source.save()
        to_target.save()
        return (to_source, to_target, vertice, way_to_intersection)

    def weight(self, params):
        '''
        Compute weight according to given parameters.
        return int
        '''
        if self.highway=='temp':
            # Rare case, probably impossible to find correct route
            # Temporary Way should be deleted
            print 'returning temp weight', self.length, self.id
            return THRESHOLD
        preferences = {'highway':MIN_WEIGHT, 'tracktype':MIN_WEIGHT, 'sac_scale':MIN_WEIGHT, 'mtbscale':MIN_WEIGHT, 'surface':MIN_WEIGHT, 'osmc':MIN_WEIGHT}
        for feature_name in preferences.keys():
            feature_value = self.__dict__[feature_name]
            if feature_value!=None and params.has_key(feature_name):
                if params[feature_name].has_key('min'):
                    try:
                        minvalue = float(params[feature_name]['min'])
                    except ValueError:
                        pass
                    else:
                        if feature_value<minvalue:
                            return MAX_WEIGHT
                if params[feature_name].has_key('max'):
                    try:
                        maxvalue = float(params[feature_name]['max'])
                    except ValueError:
                        pass
                    else:
                        if feature_value>maxvalue:
                            return MAX_WEIGHT
                try:
                    preferences[feature_name] = int(params[feature_name][str(feature_value)])
                except KeyError, ValueError:
                    preferences[feature_name] = MIN_WEIGHT
        weight = max(preferences.values())
        weight -= self._preferred_shift(params)
        weight = max(min(weight, len(WEIGHTS)), MIN_WEIGHT)
        # correct weight is at index-1 in WEIGHTS
        return WEIGHTS[weight-1]
    
    def _preferred_shift(self, params):
        '''
        Calculate preference shift for preferred or unpreferred ways
        '''
        shift = 0
        neg = 0
        if params.has_key('preferred_classes'):
            preferred_classes = params['preferred_classes']
            for p in preferred_classes:
                value = getattr(self, p)
                if value:
                    shift = max(value, shift)
                    neg = min(value, neg)
        # TODO returning neg or shift possible, see get_when_clauses TODO
        if neg < 0:
            return -1
        elif shift >0:
            return 1
        else:
            return 0

    def compute_class_id(self, class_conf):
        '''
        Compute class ID during import.
        return int
        '''
        class_id = ''
        for c in class_conf:
            classname = c['classname']
            types = c['types']
            if self.__dict__[classname]==None:
                class_id += str(c['null'])
            else:
                if classname=='incline':
                    in_percents = self.incline.replace('%', '')
                    if self.incline != in_percents:
                        try:
                            percents = float(in_percents)
                        except ValueError:
                            id = c['null']
                        else:
                            if percents>=0: id = types['positive']
                            else: id = types['negative']
                        class_id += str(id)
                        continue
                try:
                    id = types[self.__dict__[classname]]
                except KeyError:
                    print classname, 'unexpected type:', self.__dict__[classname]
                    id = c['null']
                class_id += str(id)
        return int(class_id)

    def feature(self, params, status):
        '''
        Create GeoJSON Feature object.
        return JSON like dictionary
        '''
        # weight is here a preference in the interval 1-5,
        # index of real weight defined in WEIGHTS + 1
        try:
            weight = WEIGHTS.index(self.weight(params)) + 1
        except ValueError:
            weight = len(WEIGHTS)
        return {
            'type': 'Feature',
#            'id': self.id,
            'properties': {
                'weight': weight,
                'length': self.length,
                'status': status,
                'name': self.name,
                'osm_id': self.osm_id
            },
            'geometry': json.loads(self.the_geom.geojson)
        }

    def compute_length(self):
        '''
        Compute approximate length using haversine formula.
        return length in kilometers
        '''
        coords = self.the_geom.coords
        length = 0
        for i in range(len(coords)-1):
            lon1, lat1 = coords[i]
            lon2, lat2 = coords[i+1]
            length += haversine(lon1, lat1, lon2, lat2)
        return length

class WeightCollection(models.Model):
    VEHICLE_CHOICES = (
        ('foot', 'foot'),
        ('bicycle', 'bicycle'),
    )
    name = models.CharField(max_length=40)
    oneway = models.BooleanField(default=True)
    vehicle = models.CharField(max_length=40, default='bicycle', choices=VEHICLE_CHOICES)
    
    def __unicode__(self):
        return u"%s" % (self.name)

    def get_cost_where_clause(self, params):
        '''
        Create cost column definition and where clause.
        Returns tuple (cost_clause, reverse_cost_clause, where_clause)
        '''
        where = '(id IS NOT NULL)'
        cost = 'length'
        reverse_cost = ''
        unpreferred_preferences = {1:[],2:[],3:[],4:[],5:[]}
        preferred_preferences = {1:[],2:[],3:[],4:[]}
        reverse_cases = []
        # conditions for oneways
        if self.vehicle == 'bicycle':
            # bicycles are allowed to go in some oneways reversely
            reverse_cases += ['''WHEN (bicycle!='opposite' OR bicycle IS NULL) AND reverse_cost!=length THEN reverse_cost ''']
        elif self.vehicle == 'foot':
            # consider oneway only on paths, tracks, steps and footways
            reverse_cases += ['''WHEN highway IN ('path', 'track', 'steps', 'footway') AND reverse_cost!=length THEN reverse_cost ''']
        else:
            # probably car, never route on oneway=yes
            reverse_cases += ['''WHEN reverse_cost!=length THEN reverse_cost ''']
        whereparts = []
        whereparts += self._access()
        preferred_class_names = self.preferred_set.filter(name__in=params['preferred_classes']).values_list('name', flat=True)
        for wc in self.weightclass_set.all():
            if wc.classname in params:
                unpref_dict, pref_dict = wc.get_when_clauses(params[wc.classname], preferred_class_names)
                for pref, value in pref_dict.iteritems():
                    preferred_preferences[pref] += value
                for pref, value in unpref_dict.iteritems():
                    unpreferred_preferences[pref] += value
                part = wc.get_where_clauses(params[wc.classname])
                if part:
                    whereparts.append(part)
        cases = self._create_cases(unpreferred_preferences, preferred_preferences, preferred_class_names)
        if cases:
            reverse_cases += cases
            cost = 'CASE %s ELSE "length" END' % (' '.join(cases))
        if whereparts:
            where = "(" + " AND ".join(whereparts) + ")"
        reverse_cost = 'CASE %s ELSE "length" END' % (' '.join(reverse_cases))
        return cost, reverse_cost, where
    
    def _create_cases(self, unpref, pref, preferred_class_names):
        '''
        Create array of WHEN clauses.
        '''
        pref_classes_condition = ' OR '.join([p + '>0' for p in preferred_class_names])
        cases = []
        for preference in range(4, 0, -1):
            if preferred_class_names.count() and preference>1 and pref[preference-1]:
                pref_joined_conditions = '(' + ' OR '.join(pref[preference-1]) + ') AND (' + pref_classes_condition + ')'
                cases.append('WHEN %s THEN "length"*%s' % (pref_joined_conditions, WEIGHTS[max(preference-2, 0)]))
            if unpref[preference]:
                unpref_joined_conditions = ' OR '.join(unpref[preference])
                cases.append('WHEN %s THEN "length"*%s' % (unpref_joined_conditions, WEIGHTS[preference-1]))
        return cases
    
    def _access(self):
        '''
        Create access clause according to given role (car, bike, pedestrian,...)
        '''
        # TODO: add vehicle access control, needs vehicle column in database and model
        access_clauses = []
        default_access = '''(access IS NULL OR access NOT IN ('no', 'private'))'''
        if self.vehicle in ('bicycle', 'foot'):
            access_restrictions = '''((access IS NULL OR access NOT IN ('no', 'private')) OR (access IN ('no', 'private') AND %s IN ('yes', 'designated')))''' % (self.vehicle)
            vehicle_restrictions = '''(%s IS NULL OR NOT %s IN ('no', 'private'))''' % (self.vehicle, self.vehicle)
            access_clauses += [access_restrictions, vehicle_restrictions]
        else:
            access_clauses.append(default_access)
        return access_clauses

    def dump_params(self, params):
        '''
        Dump weight collection params as JSON like dictionary.
        '''
        json = {}
        json['name'] = params['global'].get('name','undefined')
        json['oneway'] = params['global'].has_key('oneway')
        json['vehicle'] = params['global'].get('vehicle', 'bicycle')
        json['preferred'] = []
        for p in self.preferred_set.all():
            pref_class = {"name": p.name, "use": True}
            pref_class['value'] = p.name in params['preferred_classes']
            json['preferred'].append(pref_class)
        json['classes'] = []
        for c in self.weightclass_set.all():
            weight_class = {"name": c.classname, "visible": True}
            if (c.max != None) and (params[c.classname].has_key('max')):
                weight_class['max'] = params[c.classname]['max']
            if (c.min != None) and (params[c.classname].has_key('min')):
                weight_class['min'] = params[c.classname]['min']
            ws = c.weight_set.all()
            if ws.count():
                weight_class['features'] = []
                for w in c.weight_set.all():
                    weight = {"name": w.feature, "visible": True}
                    weight["value"] = params[c.classname].get(w.feature, w.preference)
                    weight_class['features'].append(weight)
            json['classes'].append(weight_class)
        return json

    
class WeightClass(models.Model):
    classname = models.CharField(max_length=40)
    collection = models.ForeignKey('WeightCollection')
    order = models.PositiveIntegerField(null=True, blank=True)
    max = models.FloatField(null=True, blank=True)
    min = models.FloatField(null=True, blank=True)
    visible = models.BooleanField(default=True)
 
    class Meta:
        ordering = ('order', 'classname',)

    def __unicode__(self):
        return u"%s, Collection: %s" % (self.classname, self.collection.name)

    def get_when_clauses(self, params, preferred_class_names):
        '''
        Create dictionaries for preferred and unpreferred cases.
        '''
        unpreferable_highways = ('track', 'path', 'bridleway')
        default = min(WEIGHTS)
        pref_dict = {1:[],2:[],3:[],4:[]}
        unpref_dict = {1:[],2:[],3:[],4:[],5:[]}
        for w in self.weight_set.all():
            try:
                preference = int(params[w.feature])
            except ValueError:
                print 'ValueError', self.classname, w.feature, params
            else:
                # TODO compute (un)preferred_class_names weights correctly, not only +/- 1 degree, but in range(-3, +3)
                if preferred_class_names.count()>0 and self.classname=='highway' and w.feature in unpreferable_highways:
                    least_when = ' OR '.join(['"' + p + '"<0' for p in preferred_class_names])
                    pref_index = min(preference+1, len(unpref_dict)) 
                    unpref_dict[pref_index].append(""" ("%s"::text='%s' AND (%s)) """ % (self.classname, w.feature, least_when))
                if preference != default:
                    if preferred_class_names.count()>0:
                        pref_dict[max(preference-1, 1)].append(""" ("%s"::text='%s') """ % (self.classname, w.feature))
                    unpref_dict[preference].append(""" ("%s"::text='%s') """ % (self.classname, w.feature))
        return unpref_dict, pref_dict

    def get_where_clauses(self, params):
        '''
        Create sql WHERE conditions.
        '''
        andparts = []
        if params.has_key('max'):
            try:
                value = float(params['max'])
                condition = '"%s"<=%s' % (self.classname, value)
            except ValueError:
                print 'ValueError', self.classname, params
            else:
                # only if smaller than default max value
                if value<self.max:
                    andparts.append(condition)
        if params.has_key('min'):
            try:
#                print 'MINVALUE:', params['min']
                value = float(params['min'])
                condition = '"%s">=%s' % (self.classname, value)
            except ValueError:
                print 'ValueError', self.classname, params
            else:
                # only if bigger than default min value
                if value>self.min:
                    andparts.append(condition)
        for w in self.weight_set.all():
            preference = params[w.feature]
            if preference=='5':
                condition = """ "%s"::text!='%s'""" % (self.classname, w.feature)
                andparts.append(condition)
        andcondition = ' AND '.join(andparts)
        if andcondition:
            return '("%s" is NULL OR (%s))' % (self.classname, andcondition)
        else:
            return

class Preferred(models.Model):
    name = models.CharField(max_length=40)
    collection = models.ForeignKey('WeightCollection')
    value = models.BooleanField(default=False)
    use = models.BooleanField(default=True)
    
    def __unicode__(self):
        return u"%s" % (self.name)


class Weight(models.Model):
    PREFERENCE_CHOICES = (
        (1, 'Ideální'),
        (2, 'Vhodné'),
        (3, 'Nevadí'),
        (4, 'Výjimečně'),
        (5, 'Vůbec'),
    )
    GUI_CHOICES = (
        ('select', 'select'),
        ('radio', 'radio'),
        ('checkbox', 'checkbox'),
    )
    classname = models.ForeignKey('WeightClass')
    feature = models.CharField(max_length=40)
    cz = models.CharField(max_length=40)
    preference = models.PositiveIntegerField(null=True, blank=True, choices=PREFERENCE_CHOICES)
    type = models.CharField(max_length=20, null=True, blank=True, choices=GUI_CHOICES)
    order = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    visible = models.BooleanField(default=True)

    class Meta:
        ordering = ('order', 'feature',)

    def __unicode__(self):
        return u"Weight(%s)" % (self.feature)

    
## PLANET_OSM_MODELS
class OsmModel(geomodels.Model):
    osm_id = models.BigIntegerField()
    
    class Meta:
        abstract = True
        
    def __unicode__(self):
        return u"OsmModel(%s)" % (self.osm_id)

    def geojson_feature(self, tags=[]):
        '''
        Create GeoJSON feature representation.
        '''
        feature = {}
        feature["type"] = "Feature"
        feature["id"] = self.id
        feature["properties"] = {"osm_id": self.osm_id}
        if self.has_geometry():
            feature["geometry"] = json.loads(self.the_geom.geojson)
        feature["properties"]["popupContent"] = self.popupContent(tags)
        feature["properties"]["label"] = self._wrapText(self.label(tags[0]), 30)
        return feature
    
    def geojson_feature_string(self, tags=[]):
        '''
        Dump GeoJSON representation as string.
        '''
        return json.dumps(self.geojson_feature(tags))
    
    def has_geometry(self):
        return hasattr(self, "the_geom") and self.the_geom != None 

    def label(self, attribute='name'):
        '''
        Value of label. Created as value for given attribute.
        '''
        if hasattr(self, attribute):
            return getattr(self, attribute)
        else:
            return ""
    
    def popupContent(self, att_list):
        '''
        Feature popup content, label created from first item in attribute 
        list is used as heading.
        '''
        content = ''
        if len(att_list)>0:
            header = self.label(att_list[0])
            if header:
                content += '<h3>%s</h3>' % (header)
            content += '<p class="geojsonPopup">'
            for attr in att_list[1:]:
                if hasattr(self, attr) and getattr(self, attr):
                    content += '%s: %s <br>' % (attr, getattr(self, attr))
            content += 'OSM ID: %s' % (self.osmLink())
            content += '</p>'
        else:
            content += '<h2>%s</h2>' % (self.osmLink())
        return content
    
    def osmLink(self, url='http://www.openstreetmap.org/browse/', geometry='way'):
        '''
        HTML anchor linking to OSM browse page by default.
        '''
        if self.osm_id < 0:
            # hacked 32 bit integer problem, osm_id is negative
            if geometry == 'node':
                self.osm_id += 2**32
            else:
                # osm_id is negative if it is a relation
                self.osm_id = abs(self.osm_id)
                geometry = 'relation'
        href = '%s%s/%s' % (url, geometry, self.osm_id)
        return '<a target="_blank" href="%s">%s</a>' % (href, self.osm_id)
    
    def _wrapText(self, text, width=70, wrap_str='<br>'):
        if text:
            return wrap_str.join(wrap(text, width))
        else:
            return ''
        

class OsmPoint(OsmModel):
    the_geom = geomodels.PointField()
    name = models.CharField(max_length=400, null=True, blank=True)
    amenity = models.CharField(max_length=200, null=True, blank=True)
    ele = models.CharField(max_length=200, null=True, blank=True)
    highway = models.CharField(max_length=200, null=True, blank=True)
    historic = models.CharField(max_length=200, null=True, blank=True)
    information = models.CharField(max_length=200, null=True, blank=True)
    leisure = models.CharField(max_length=200, null=True, blank=True)
    man_made = models.CharField(max_length=200, null=True, blank=True)
    natural = models.CharField(max_length=200, null=True, blank=True)
    noexit = models.CharField(max_length=200, null=True, blank=True)
    opening_hours = models.CharField(max_length=200, null=True, blank=True)
    place = models.CharField(max_length=200, null=True, blank=True)
    protect_class = models.CharField(max_length=200, null=True, blank=True)
    railway = models.CharField(max_length=200, null=True, blank=True)
    ref = models.CharField(max_length=200, null=True, blank=True)
    ruins = models.CharField(max_length=200, null=True, blank=True)
    shop = models.CharField(max_length=200, null=True, blank=True)
    sport = models.CharField(max_length=200, null=True, blank=True)
    tourism = models.CharField(max_length=200, null=True, blank=True)

    objects = geomodels.GeoManager()
    
    def osmLink(self, url='http://www.openstreetmap.org/browse/', geometry='node'):
        return super(OsmPoint, self).osmLink(url, geometry)
    
class OsmLine(OsmModel):
    the_geom = geomodels.LineStringField()
    name = models.CharField(max_length=400, null=True, blank=True)
    mtbscale = models.CharField(verbose_name='mtb:scale', max_length=200, null=True, blank=True)
    mtbdescription = models.CharField(verbose_name='mtb:description', max_length=200, null=True, blank=True)
    mtbscaleuphill = models.CharField(verbose_name='mtb:scale:uphill', max_length=200, null=True, blank=True)
    
    objects = geomodels.GeoManager()
    

class GeojsonLayer(models.Model):
    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=40)
    filter = models.TextField(null=True, blank=True)
    pointGeom = models.BooleanField(default=False)
    lineGeom = models.BooleanField(default=False)
    polygonGeom = models.BooleanField(default=False)
    attributes = models.TextField(null=True, blank=True)
#    minZoom = models.PositiveIntegerField(default=13)
#    maxZoom = models.PositiveIntegerField(default=18)

    def __unicode__(self):
        return u"%s" % (self.name)
    
    def attributes_list(self):
        '''
        Cast attributes string to list.
        '''
        return [attr.strip() for attr in self.attributes.split(',')]
    
    def geojson_feature_collection(self, bbox=[-180.0, -90.0, 180.0, 90.0]):
        '''
        Create geojson feature collection with instances that intersects
        given bounding box.
        '''
        bounding_box = Polygon.from_bbox(bbox)
        filter = json.loads(self.filter)
        att_list = self.attributes_list()
        features = []
        if self.pointGeom:
            points = OsmPoint.objects.filter(the_geom__bboverlaps=bounding_box).filter(**filter)[:200]
            features += [point.geojson_feature(att_list) for point in points]
        if self.lineGeom:
            lines = OsmLine.objects.filter(the_geom__bboverlaps=bounding_box).filter(**filter)[:200]
            features += [line.geojson_feature(att_list) for line in lines]
        feature_collection = {
            "type":"FeatureCollection",
            "features":features
        }
        return json.dumps(feature_collection)
        

class RoutingEvaluation(models.Model):
    EVALUATION_CHOICES = (
        (1, 'Dokonalé'),
        (2, 'Dobré'),
        (3, 'Použitelné'),
        (4, 'Špatné'),
        (5, 'Nepoužitelné'),
    )
    SPEED_CHOICES = (
        (1, 'Nijak neomezuje'),
        (2, 'Pomalé, ale rád si počkám'),
        (3, 'Pomalé, nepoužitelné'),
    )
    QUALITY_CHOICES = (
        (1, 'Vyhovuje'),
        (2, 'Dobré, ale chci více parametrů'),
        (3, 'Dobré, ale občas po cestách, které nechci'),
        (4, 'Špatné, nevhodně nalezená trasa'),
        (5, 'Špatné, nechápu proč se to takto chová'),
    )
    params = models.TextField()
    linestring = models.TextField()
    timestamp = models.DateTimeField()
    general_evaluation = models.PositiveIntegerField(verbose_name='Celkové hodnocení', choices=EVALUATION_CHOICES, default=3)
    speed = models.PositiveIntegerField(verbose_name='Rychlost', choices=SPEED_CHOICES, default=2)
    quality = models.PositiveIntegerField(verbose_name='Kvalita tras', choices=QUALITY_CHOICES, default=1)
    comment = models.TextField(verbose_name='Komentář', null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    
    def __unicode__(self):
        return u"%s, From: %s, Comment: '%s')" % (self.timestamp.date(), self.email, self.comment[:40])


def verbose_name(obj, field_name, underscores=False):
    '''
    Get verbose name of model field with or without underscores
    instead of spaces.
    '''
    verbose_name = obj._meta.get_field_by_name(field_name)[0].verbose_name
    if underscores:
        return verbose_name.replace(' ', '_')
    else:
        return verbose_name

def verbose_names(obj, underscores=False):
    '''
    Get list of all object fields verbose names with or without underscores
    instead of spaces.
    '''
    names = obj._meta.get_all_field_names()
    return [verbose_name(obj, name, underscores) for name in names]

    