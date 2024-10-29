
from flask import Flask, render_template, jsonify, request
import requests
import folium
from folium import plugins
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import json
import branca.colormap as cm
from threading import Lock
import time

# enable logging
app = Flask(__name__)
app.logger.setLevel('DEBUG')

class EONETData:
    def __init__(self):
        self.EONET_API = "https://eonet.gsfc.nasa.gov/api/v3"
        self.events_cache = None
        self.categories_cache = None
        self.last_update = None
        self.update_interval = 300  # 5 minutes
        self.data_lock = Lock()
        self.initialized = False

        # Initialize colormap for events
        self.colormap = cm.LinearColormap(
            colors=['#FFEB3B', '#FF9800', '#F44336'],
            vmin=0, vmax=10,
            caption='Event Magnitude'
        )

        # Initialize data
        self.initialize()

    def initialize(self):
        """Initialize data"""
        print("Starting initial data load...")
        try:
            self.fetch_categories()
            self.fetch_events()
            self.initialized = True
            print("Initial data load completed successfully")
            return True
        except Exception as e:
            print(f"Error during initial data load: {e}")
            return False

    def fetch_events(self, days=365):
        """Fetch events from EONET API"""
        try:
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=days)

            params = {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d'),
                'status': 'all'
            }

            response = requests.get(f"{self.EONET_API}/events", params=params)
            response.raise_for_status()

            with self.data_lock:
                self.events_cache = response.json()
                self.last_update = datetime.now()

            return True
        except Exception as e:
            print(f"Error fetching events: {e}")
            return False

    def fetch_categories(self):
        """Fetch categories from EONET API"""
        try:
            response = requests.get(f"{self.EONET_API}/categories")
            response.raise_for_status()
            self.categories_cache = response.json()
            return True
        except Exception as e:
            print(f"Error fetching categories: {e}")
            return False

    def get_filtered_events(self, start_date=None, end_date=None, event_type=None,
                        min_magnitude=None, max_magnitude=None):
        """Get filtered events based on criteria"""
        if not self.events_cache:
            return {"events": []}

        filtered_events = []
        for event in self.events_cache.get('events', []):
            try:
                # Apply date and type filters
                if start_date and event['geometry'][0]['date'][:10] < start_date:
                    continue
                if end_date and event['geometry'][0]['date'][:10] > end_date:
                    continue
                if event_type and event['categories'][0]['id'] != event_type:
                    continue

                # Initialize magnitude as None
                magnitude = None

                # Try to get magnitude from event root
                if 'magnitudeValue' in event:
                    try:
                        mag_value = event.get('magnitudeValue')
                        if mag_value is not None and str(mag_value).strip():
                            magnitude = float(mag_value)
                    except (ValueError, TypeError):
                        pass

                # Try to get magnitude from geometry if not found in root
                if magnitude is None and event.get('geometry'):
                    for geo in event['geometry']:
                        try:
                            mag_value = geo.get('magnitudeValue')
                            if mag_value is not None and str(mag_value).strip():
                                magnitude = float(mag_value)
                                break
                        except (ValueError, TypeError):
                            continue

                # Apply magnitude filters if magnitude exists
                if magnitude is not None and (min_magnitude is not None or max_magnitude is not None):
                    if min_magnitude and magnitude < float(min_magnitude):
                        continue
                    if max_magnitude and magnitude > float(max_magnitude):
                        continue

                filtered_events.append(event)

            except Exception as e:
                print(f"Error filtering event: {str(e)}")
                continue

        return {"events": filtered_events}

    def create_map(self, events):
        """Create enhanced Folium map with events"""
        m = folium.Map(
            location=[20, 0],
            zoom_start=3,
            tiles='OpenStreetMap',
            prefer_canvas=True
        )

        # Create feature groups for different event types
        event_groups = {}

        for event in events.get('events', []):
            if event.get('geometry') and event['geometry'][0].get('coordinates'):
                coords = event['geometry'][0]['coordinates']
                category = event['categories'][0]['title']

                # Initialize magnitude to 0
                magnitude = 0

                # Iterate over the geometry array to find the magnitudeValue
                for geom in event['geometry']:
                    if 'magnitudeValue' in geom:
                        if geom.get('magnitudeValue') is not None:
                            magnitude = float(geom['magnitudeValue'])
                        else:
                            magnitude = 0
                        # Determine icon and color based on category and magnitude
                        icon_color = self.get_magnitude_color(magnitude)
                        icon = self.get_category_icon(category)

                        # Create feature group for category if not exists
                        if category not in event_groups:
                            event_groups[category] = folium.FeatureGroup(name=category)

                        # Create popup content
                        popup_content = f"""
                            <div style="width: 300px">
                                <h4>{event['title']}</h4>
                                <p><b>Category:</b> {category}</p>
                                <p><b>Date:</b> {event['geometry'][0]['date'][:10]}</p>
                                {'<p><b>Magnitude:</b> ' + str(magnitude) + '</p>' if magnitude else ''}
                                <p><b>Description:</b> {event.get('description', 'No description available')}</p>
                            </div>
                        """

                        # Add marker
                        folium.CircleMarker(
                            location=[coords[1], coords[0]],
                            radius=8,
                            popup=folium.Popup(popup_content, max_width=300),
                            color='black',
                            weight=1,
                            fill=True,
                            fill_color=icon_color,
                            fill_opacity=0.7
                        ).add_to(event_groups[category])

        # Add feature groups to map
        for group in event_groups.values():
            group.add_to(m)

        # Add layer control to map
        folium.LayerControl().add_to(m)

        return m._repr_html_()

    def get_magnitude_color(self, magnitude):
        """Determine color based on magnitude"""
        if magnitude == 0 or magnitude is None:
            return '#FFEB3B'  # Default blue
        if magnitude < 3:
            return '#FFEB3B'  # Yellow
        if magnitude < 6:
            return '#FF9800'  # Orange
        return '#F44336'  # Red

    def get_category_icon(self, category):
        """Get appropriate icon for category"""
        icons = {
            'Wildfires': 'fire',
            'Volcanoes': 'mountain',
            'Severe Storms': 'bolt',
            'Floods': 'water',
            'Earthquakes': 'globe',
            'Drought': 'sun',
            'Landslides': 'mountain',
            'Sea and Lake Ice': 'snowflake',
            'Temperature Extremes': 'thermometer'
        }
        return icons.get(category, 'info-circle')

    def get_summary_statistics(self):
        """Generate summary statistics"""
        stats = {
            'event_count': 0,
            'categories': {},
            'magnitudes': {
                'low': 0,    # 0-1.5
                'medium': 0, # 1.5-5
                'high': 0    # 5+
            },
            'daily_counts': {}
        }

        if not self.events_cache:
            return stats

        stats['event_count'] = len(self.events_cache['events'])

        for event in self.events_cache['events']:
            try:
                # Category statistics
                category = event['categories'][0]['title']
                stats['categories'][category] = stats['categories'].get(category, 0) + 1

                # Daily counts
                date = event['geometry'][0]['date'][:10]
                stats['daily_counts'][date] = stats['daily_counts'].get(date, 0) + 1

                # Magnitude statistics
                # Check for magnitude in both possible locations
                magnitude = None
                mag_id = None

                # Check in event root
                if 'magnitudeValue' in event and 'magnitudeUnit' in event:
                    magnitude = float(event['magnitudeValue'])
                    mag_id = event.get('magnitudeUnit')

                # Check in geometry
                elif event.get('geometry', []):
                    for geo in event['geometry']:
                        if 'magnitudeValue' in geo and 'magnitudeUnit' in geo:
                            magnitude = float(geo['magnitudeValue'])
                            mag_id = geo.get('magnitudeUnit')
                            break

                # Categorize magnitude if found
                if magnitude is not None:
                    print(f"Processing magnitude: {magnitude}, Unit: {mag_id}")  # Debug print
                    if magnitude < 1.5:
                        stats['magnitudes']['low'] += 1
                    elif magnitude < 5.0:
                        stats['magnitudes']['medium'] += 1
                    else:
                        stats['magnitudes']['high'] += 1
                else:
                    # If no magnitude found, count as low
                    stats['magnitudes']['low'] += 1

            except Exception as e:
                print(f"Error processing event: {e}")
                continue

        # Debug print
        print("Magnitude statistics:", stats['magnitudes'])

        return stats

    def get_trend_analysis(self, category=None, period='monthly'):
        """Analyze trends in event frequency"""
        events = self.get_filtered_events(event_type=category)

        # Group events by period
        periods = {}
        for event in events['events']:
            date = datetime.strptime(event['geometry'][0]['date'][:10], '%Y-%m-%d')
            if period == 'monthly':
                key = date.strftime('%Y-%m')
            elif period == 'weekly':
                key = date.strftime('%Y-W%W')
            else:
                key = date.strftime('%Y-%m-%d')

            periods[key] = periods.get(key, 0) + 1

        # Calculate trends
        counts = list(periods.values())
        if len(counts) > 1:
            trend = (counts[-1] - counts[0]) / len(counts)
        else:
            trend = 0

        return {
            'periods': list(periods.keys()),
            'counts': counts,
            'trend': trend,
            'average': sum(counts) / len(counts) if counts else 0,
            'max': max(counts) if counts else 0,
            'min': min(counts) if counts else 0
        }

   
    #ANALYSIS
    def get_analysis_data(self, period=30):
        """Get comprehensive analysis data"""
        try:
            # Calculate date range
            end_date = datetime.now(timezone.utc)
            start_date = (end_date - timedelta(days=int(period))).strftime('%Y-%m-%d')
            
            # Get filtered events
            events = self.get_filtered_events(start_date=start_date)
            print(f"Total events fetched: {len(events.get('events', []))}")  # Debug log
            
            data = {
                'trends': {'labels': [], 'values': []},
                'categories': {'labels': [], 'values': []},
                'geographic': {},
                'severity': {
                    'wildfires': [],
                    'storms': [],
                    'volcanoes': [],
                    'earthquakes': []
                },
                'weekday': {
                    'labels': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
                    'values': [0] * 7
                }
            }
            
            category_counts = {}
            dates_count = {}
            
            # Debug counters
            severity_counts = {
                'wildfires': 0,
                'storms': 0,
                'volcanoes': 0,
                'earthquakes': 0
            }

            for event in events.get('events', []):
                try:
                    date = event['geometry'][0]['date'][:10]
                    categories = [cat['title'] for cat in event['categories']]
                    
                    # Process basic counts
                    for category in categories:
                        category_counts[category] = category_counts.get(category, 0) + 1
                    dates_count[date] = dates_count.get(date, 0) + 1

                    # Geographic and weekday processing
                    if event['geometry']:
                        coords = event['geometry'][0]['coordinates']
                        region = self.get_region_name(coords[1])
                        data['geographic'][region] = data['geographic'].get(region, 0) + 1
                        
                        weekday = datetime.strptime(date, '%Y-%m-%d').weekday()
                        data['weekday']['values'][weekday] += 1

                    # Process magnitude/severity
                    magnitude_value = None
                    magnitude_unit = None

                    # Check for magnitude in event root
                    if 'magnitudeValue' in event:
                        magnitude_value = event['magnitudeValue']
                        magnitude_unit = event.get('magnitudeUnit', '')
                    
                    # Check for magnitude in geometries
                    if not magnitude_value and event.get('geometry'):
                        for geo in event['geometry']:
                            if 'magnitudeValue' in geo:
                                magnitude_value = geo['magnitudeValue']
                                magnitude_unit = geo.get('magnitudeUnit', '')
                                break

                    # Debug print
                    print(f"Event: {event.get('title')} - Categories: {categories}")
                    print(f"Magnitude: {magnitude_value}, Unit: {magnitude_unit}")

                    if magnitude_value is not None:
                        try:
                            magnitude_value = float(magnitude_value)
                            event_data = {
                                'date': date,
                                'magnitude': magnitude_value,
                                'unit': magnitude_unit,
                                'title': event.get('title', ''),
                                'description': event.get('description', '')
                            }

                            # Categorize based on event categories
                            if any('Wildfires' in cat for cat in categories):
                                data['severity']['wildfires'].append(event_data)
                                severity_counts['wildfires'] += 1
                                
                            elif any(storm_type in cat for cat in categories 
                                for storm_type in ['Severe Storms', 'Tropical Cyclones']):
                                data['severity']['storms'].append(event_data)
                                severity_counts['storms'] += 1
                                
                            elif any('Volcanoes' in cat for cat in categories):
                                data['severity']['volcanoes'].append(event_data)
                                severity_counts['volcanoes'] += 1
                                
                            elif any('Earthquakes' in cat for cat in categories):
                                data['severity']['earthquakes'].append(event_data)
                                severity_counts['earthquakes'] += 1

                        except (ValueError, TypeError) as e:
                            print(f"Error converting magnitude value: {e}")
                            continue

                except Exception as e:
                    print(f"Error processing event: {e}")
                    continue

            # Debug print severity counts
            print("Severity counts:", severity_counts)

            # Sort and prepare trend data
            sorted_dates = sorted(dates_count.keys())
            data['trends']['labels'] = sorted_dates
            data['trends']['values'] = [dates_count[date] for date in sorted_dates]

            # Prepare category data
            data['categories']['labels'] = list(category_counts.keys())
            data['categories']['values'] = list(category_counts.values())

            return data

        except Exception as e:
            print(f"Error in analysis data: {e}")
            return {
                'trends': {'labels': [], 'values': []},
                'categories': {'labels': [], 'values': []},
                'geographic': {},
                'severity': {
                    'wildfires': [],
                    'storms': [],
                    'volcanoes': [],
                    'earthquakes': []
                },
                'weekday': {
                    'labels': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
                    'values': [0] * 7
                }
            }
    def convert_acres_to_nm2(self, acres):
        """Convert acres to square kilometers"""
        return acres * 0.00404686

    def get_region_name(self, lat):
        """Get region name based on latitude"""
        if lat > 66.5: return 'Arctic'
        elif lat > 23.5: return 'Northern Hemisphere'
        elif lat > 0: return 'Tropics (North)'
        elif lat > -23.5: return 'Tropics (South)'
        elif lat > -66.5: return 'Southern Hemisphere'
        else: return 'Antarctic'

# Initialize EONET data handler
eonet_data = EONETData()

@app.route('/')
def index():
    """Main dashboard route"""
    events = eonet_data.get_filtered_events()
    map_html = eonet_data.create_map(events)
    return render_template('index.html', map_html=map_html)

@app.route('/trends')
def trends():
    """Trends analysis route"""
    return render_template('trends.html')

@app.route('/api/events')
def get_events():
    """API endpoint for events"""
    params = {
        'start_date': request.args.get('start_date'),
        'end_date': request.args.get('end_date'),
        'event_type': request.args.get('event_type'),
        'min_magnitude': request.args.get('min_magnitude'),
        'max_magnitude': request.args.get('max_magnitude')
    }
    return jsonify(eonet_data.get_filtered_events(**params))

@app.route('/api/map')
def get_map():
    """API endpoint for map"""
    params = {
        'start_date': request.args.get('start_date'),
        'end_date': request.args.get('end_date'),
        'event_type': request.args.get('event_type'),
        'min_magnitude': request.args.get('min_magnitude'),
        'max_magnitude': request.args.get('max_magnitude')
    }
    events = eonet_data.get_filtered_events(**params)
    return eonet_data.create_map(events)

@app.route('/api/summary')
def get_summary():
    """API endpoint for summary statistics"""
    return jsonify(eonet_data.get_summary_statistics())

@app.route('/api/categories')
def get_categories():
    """API endpoint for categories"""
    return jsonify(eonet_data.categories_cache or {'categories': []})

@app.route('/api/trends')
def get_trends():
    """API endpoint for trend analysis"""
    category = request.args.get('category')
    period = request.args.get('period', 'monthly')
    return jsonify(eonet_data.get_trend_analysis(category, period))


# Add these new routes to your existing Flask app
@app.route('/analysis')
def analysis():
    """Analysis dashboard route"""
    return render_template('analysis.html')

@app.route('/api/analysis/data')
def get_analysis_data():
    """Get all analysis data"""
    period = request.args.get('period',365)
    data = eonet_data.get_analysis_data(period=int(period))
    return jsonify(data)

if __name__ == '__main__':
    app.run(debug=True)
