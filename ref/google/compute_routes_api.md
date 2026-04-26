## Introduction

Compute Routes is a method in the Routes API service that accepts
an HTTPS request and returns the ideal route between two locations.
Provide directions with real-time traffic for transit, biking, driving,
2-wheel motorized vehicles, or walking between multiple locations.

**Need Route Matrixes?** If you are interested in a route matrix, see
[Compute Route Matrix Overview](https://developers.google.com/maps/documentation/routes/compute-route-matrix-over).

**Migrating?** If you are migrating from the Distance Matrix API (Legacy),
see migration instructions starting with
[Why migrate to the Routes API](https://developers.google.com/maps/documentation/routes/migrate-routes-why).

## Why use Compute Routes

With Compute Routes, with a wide
range of route details you can route your vehicles or packages according to
your preferences while optimizing for cost and quality.

## What you can do with Compute Routes?

With the Routes API `Compute Routes` method, you can
do the following things:

- **Get directions for different ways to travel**, and for a single or
  multiple destinations:

  - Modes of transportation: transit, driving, two-wheel vehicles,
    walking, or bicycling.

  - A series of waypoints that you can optimize for the most efficient
    order in which to travel to them.

- **Use multiple ways to specify origins, destinations, and waypoints**:

  - Text strings. For example: "Chicago, IL", "Darwin, NT, Australia", "1800
    Amphitheatre Parkway, Mountain View, CA 94043", or "CWF6+FWX Mountain
    View, California"

  - Place IDs

  - Latitude and longitude coordinates, optionally with vehicle heading

- **Fine-tune your route options** based on your needs and goals:

  - Select fuel or energy-efficient routes for your vehicle's engine type:
    Diesel, Electric, Hybrid, Gas. For more information, see
    [Get an eco-friendly route](https://developers.google.com/maps/documentation/routes/eco-routes#request_an_eco-friendly_route).

  - Set fine-grained options for traffic calculation, letting you make
    quality versus latency trade off decisions. For details, see
    [Specify how and if to include traffic data](https://developers.google.com/maps/documentation/routes/config_trade_offs).

  - Set vehicle heading (direction of travel) and side-of-road information
    for waypoints to increase ETA accuracy. For details, see
    [Specify vehicle heading and side of road](https://developers.google.com/maps/documentation/routes/location_modifiers).

  - Specify pass-through versus terminal locations and safe stopover
    locations. For details, see [Set a stop along a route](https://developers.google.com/maps/documentation/routes/stop_over) and
    [Set a point for a route to pass through](https://developers.google.com/maps/documentation/routes/pass-through).

  - Request toll information, along with route distance and ETA. For
    details, see
    [Calculate toll fees for a route](https://developers.google.com/maps/documentation/routes/calculate_toll_fees).

- **Control your latency and quality** by requesting only the data you need
  using a field mask, which helps you avoid unnecessary processing time and
  higher request billing rates. For details, see
  [Choose what information to return](https://developers.google.com/maps/documentation/routes/choose_fields).

## How Compute Routes works

The Routes API `ComputeRoutes` method accepts an HTTP POST request with
a JSON request body that contains the request details. Required are an origin,
destination, `travelMode`, and a field mask to specify which fields to return.

#### Example

```json
curl -X POST -d '{
    "origin": {
      "address": "1800 Amphitheatre Parkway, Mountain View, CA 94043"
    },
    "destination": {
      "address": "Sloat Blvd &, Upper Great Hwy, San Francisco, CA 94132"
    },
  "travelMode": "DRIVE"
  }' \
  -H 'Content-Type: application/json' -H 'X-Goog-Api-Key: YOUR_API_KEY' \
  -H 'X-Goog-FieldMask: routes.duration,routes.distanceMeters' \
  'https://routes.googleapis.com/directions/v2:computeRoutes'
```

The service then calculates the requested route, and returns the fields you've
requested.

### Resources

The following table summarizes the resources available through the
Routes API Compute Routes method,
along with the data it returns.

<br />

| Data resources | Data returned | Return format |
|---|---|---|
| [ComputeRoutes](https://developers.google.com/maps/documentation/routes/compute_route_directions) | Returns routes, legs, and steps for a route, with alternate routes, if requested. | JSON |

<br />

### How to use Compute Routes

|---|---|---|
| 1 | **Get set up** | Start with [Set up your Google Cloud project](https://developers.google.com/maps/documentation/routes/cloud-setup) and complete the setup instructions that follow. |
| 2 | **Understand how the Routes API bills** | For information, see [Usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing). |
| 3 | **Compute a route and review the response** | For more information, see [Get a route](https://developers.google.com/maps/documentation/routes/compute_route_directions) and [Review the route responses](https://developers.google.com/maps/documentation/routes/understand-route-response). |

### Available client libraries

For a list of the available client libraries for
Compute Routes, see
[Client libraries](https://developers.google.com/maps/documentation/routes/client-libraries).

## What's next

- [Get a route](https://developers.google.com/maps/documentation/routes/compute_route_directions)
- [Available route options](https://developers.google.com/maps/documentation/routes/route-opt)
- [Choose what information to return](https://developers.google.com/maps/documentation/routes/choose_fields)
- [Migrate from Directions API (Legacy)](https://developers.google.com/maps/documentation/routes/migrate-routes)
- [Migrate from the Routes API preview to GA](https://developers.google.com/maps/documentation/routes/migrate-routes-preview)

    **European Economic Area (EEA) developers**

> [!NOTE]
> If your billing address is in the European Economic Area, effective on 8 July 2025, the [Google Maps Platform EEA Terms of Service](https://cloud.google.com/terms/maps-platform/eea) will apply to your use of the Services. Functionality varies by region. [Learn more](https://developers.google.com/maps/comms/eea/faq).

[![](https://developers.google.com/static/maps/documentation/routes/images/routes_over.png "Try the demo")](https://developers.google.com/maps/documentation/routes/demo)

## Introduction

Compute Routes is a method in the Routes API service that accepts
an HTTPS request and returns the ideal route between two locations.
Provide directions with real-time traffic for transit, biking, driving,
2-wheel motorized vehicles, or walking between multiple locations.

**Need Route Matrixes?** If you are interested in a route matrix, see
[Compute Route Matrix Overview](https://developers.google.com/maps/documentation/routes/compute-route-matrix-over).

**Migrating?** If you are migrating from the Distance Matrix API (Legacy),
see migration instructions starting with
[Why migrate to the Routes API](https://developers.google.com/maps/documentation/routes/migrate-routes-why).

## Why use Compute Routes

With Compute Routes, with a wide
range of route details you can route your vehicles or packages according to
your preferences while optimizing for cost and quality.

## What you can do with Compute Routes?

With the Routes API `Compute Routes` method, you can
do the following things:

- **Get directions for different ways to travel**, and for a single or
  multiple destinations:

  - Modes of transportation: transit, driving, two-wheel vehicles,
    walking, or bicycling.

  - A series of waypoints that you can optimize for the most efficient
    order in which to travel to them.

- **Use multiple ways to specify origins, destinations, and waypoints**:

  - Text strings. For example: "Chicago, IL", "Darwin, NT, Australia", "1800
    Amphitheatre Parkway, Mountain View, CA 94043", or "CWF6+FWX Mountain
    View, California"

  - Place IDs

  - Latitude and longitude coordinates, optionally with vehicle heading

- **Fine-tune your route options** based on your needs and goals:

  - Select fuel or energy-efficient routes for your vehicle's engine type:
    Diesel, Electric, Hybrid, Gas. For more information, see
    [Get an eco-friendly route](https://developers.google.com/maps/documentation/routes/eco-routes#request_an_eco-friendly_route).

  - Set fine-grained options for traffic calculation, letting you make
    quality versus latency trade off decisions. For details, see
    [Specify how and if to include traffic data](https://developers.google.com/maps/documentation/routes/config_trade_offs).

  - Set vehicle heading (direction of travel) and side-of-road information
    for waypoints to increase ETA accuracy. For details, see
    [Specify vehicle heading and side of road](https://developers.google.com/maps/documentation/routes/location_modifiers).

  - Specify pass-through versus terminal locations and safe stopover
    locations. For details, see [Set a stop along a route](https://developers.google.com/maps/documentation/routes/stop_over) and
    [Set a point for a route to pass through](https://developers.google.com/maps/documentation/routes/pass-through).

  - Request toll information, along with route distance and ETA. For
    details, see
    [Calculate toll fees for a route](https://developers.google.com/maps/documentation/routes/calculate_toll_fees).

- **Control your latency and quality** by requesting only the data you need
  using a field mask, which helps you avoid unnecessary processing time and
  higher request billing rates. For details, see
  [Choose what information to return](https://developers.google.com/maps/documentation/routes/choose_fields).

## How Compute Routes works

The Routes API `ComputeRoutes` method accepts an HTTP POST request with
a JSON request body that contains the request details. Required are an origin,
destination, `travelMode`, and a field mask to specify which fields to return.

#### Example

```json
curl -X POST -d '{
    "origin": {
      "address": "1800 Amphitheatre Parkway, Mountain View, CA 94043"
    },
    "destination": {
      "address": "Sloat Blvd &, Upper Great Hwy, San Francisco, CA 94132"
    },
  "travelMode": "DRIVE"
  }' \
  -H 'Content-Type: application/json' -H 'X-Goog-Api-Key: YOUR_API_KEY' \
  -H 'X-Goog-FieldMask: routes.duration,routes.distanceMeters' \
  'https://routes.googleapis.com/directions/v2:computeRoutes'
```

The service then calculates the requested route, and returns the fields you've
requested.

### Resources

The following table summarizes the resources available through the
Routes API Compute Routes method,
along with the data it returns.

<br />

| Data resources | Data returned | Return format |
|---|---|---|
| [ComputeRoutes](https://developers.google.com/maps/documentation/routes/compute_route_directions) | Returns routes, legs, and steps for a route, with alternate routes, if requested. | JSON |

<br />

### How to use Compute Routes

|---|---|---|
| 1 | **Get set up** | Start with [Set up your Google Cloud project](https://developers.google.com/maps/documentation/routes/cloud-setup) and complete the setup instructions that follow. |
| 2 | **Understand how the Routes API bills** | For information, see [Usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing). |
| 3 | **Compute a route and review the response** | For more information, see [Get a route](https://developers.google.com/maps/documentation/routes/compute_route_directions) and [Review the route responses](https://developers.google.com/maps/documentation/routes/understand-route-response). |

### Available client libraries

For a list of the available client libraries for
Compute Routes, see
[Client libraries](https://developers.google.com/maps/documentation/routes/client-libraries).

## What's next

- [Get a route](https://developers.google.com/maps/documentation/routes/compute_route_directions)
- [Available route options](https://developers.google.com/maps/documentation/routes/route-opt)
- [Choose what information to return](https://developers.google.com/maps/documentation/routes/choose_fields)
- [Migrate from Directions API (Legacy)](https://developers.google.com/maps/documentation/routes/migrate-routes)
- [Migrate from the Routes API preview to GA](https://developers.google.com/maps/documentation/routes/migrate-routes-preview)

**European Economic Area (EEA) developers**

> [!NOTE]
> If your billing address is in the European Economic Area, effective on 8 July 2025, the [Google Maps Platform EEA Terms of Service](https://cloud.google.com/terms/maps-platform/eea) will apply to your use of the Services. Functionality varies by region. [Learn more](https://developers.google.com/maps/comms/eea/faq).

[![](https://developers.google.com/static/maps/documentation/routes/images/routes_over.png "Try the demo")](https://developers.google.com/maps/documentation/routes/demo)

## Introduction

Compute Routes is a method in the Routes API service that accepts
an HTTPS request and returns the ideal route between two locations.
Provide directions with real-time traffic for transit, biking, driving,
2-wheel motorized vehicles, or walking between multiple locations.

**Need Route Matrixes?** If you are interested in a route matrix, see
[Compute Route Matrix Overview](https://developers.google.com/maps/documentation/routes/compute-route-matrix-over).

**Migrating?** If you are migrating from the Distance Matrix API (Legacy),
see migration instructions starting with
[Why migrate to the Routes API](https://developers.google.com/maps/documentation/routes/migrate-routes-why).

## Why use Compute Routes

With Compute Routes, with a wide
range of route details you can route your vehicles or packages according to
your preferences while optimizing for cost and quality.

## What you can do with Compute Routes?

With the Routes API `Compute Routes` method, you can
do the following things:

- **Get directions for different ways to travel**, and for a single or
  multiple destinations:

  - Modes of transportation: transit, driving, two-wheel vehicles,
    walking, or bicycling.

  - A series of waypoints that you can optimize for the most efficient
    order in which to travel to them.

- **Use multiple ways to specify origins, destinations, and waypoints**:

  - Text strings. For example: "Chicago, IL", "Darwin, NT, Australia", "1800
    Amphitheatre Parkway, Mountain View, CA 94043", or "CWF6+FWX Mountain
    View, California"

  - Place IDs

  - Latitude and longitude coordinates, optionally with vehicle heading

- **Fine-tune your route options** based on your needs and goals:

  - Select fuel or energy-efficient routes for your vehicle's engine type:
    Diesel, Electric, Hybrid, Gas. For more information, see
    [Get an eco-friendly route](https://developers.google.com/maps/documentation/routes/eco-routes#request_an_eco-friendly_route).

  - Set fine-grained options for traffic calculation, letting you make
    quality versus latency trade off decisions. For details, see
    [Specify how and if to include traffic data](https://developers.google.com/maps/documentation/routes/config_trade_offs).

  - Set vehicle heading (direction of travel) and side-of-road information
    for waypoints to increase ETA accuracy. For details, see
    [Specify vehicle heading and side of road](https://developers.google.com/maps/documentation/routes/location_modifiers).

  - Specify pass-through versus terminal locations and safe stopover
    locations. For details, see [Set a stop along a route](https://developers.google.com/maps/documentation/routes/stop_over) and
    [Set a point for a route to pass through](https://developers.google.com/maps/documentation/routes/pass-through).

  - Request toll information, along with route distance and ETA. For
    details, see
    [Calculate toll fees for a route](https://developers.google.com/maps/documentation/routes/calculate_toll_fees).

- **Control your latency and quality** by requesting only the data you need
  using a field mask, which helps you avoid unnecessary processing time and
  higher request billing rates. For details, see
  [Choose what information to return](https://developers.google.com/maps/documentation/routes/choose_fields).

## How Compute Routes works

The Routes API `ComputeRoutes` method accepts an HTTP POST request with
a JSON request body that contains the request details. Required are an origin,
destination, `travelMode`, and a field mask to specify which fields to return.

#### Example

```json
curl -X POST -d '{
    "origin": {
      "address": "1800 Amphitheatre Parkway, Mountain View, CA 94043"
    },
    "destination": {
      "address": "Sloat Blvd &, Upper Great Hwy, San Francisco, CA 94132"
    },
  "travelMode": "DRIVE"
  }' \
  -H 'Content-Type: application/json' -H 'X-Goog-Api-Key: YOUR_API_KEY' \
  -H 'X-Goog-FieldMask: routes.duration,routes.distanceMeters' \
  'https://routes.googleapis.com/directions/v2:computeRoutes'
```

The service then calculates the requested route, and returns the fields you've
requested.

### Resources

The following table summarizes the resources available through the
Routes API Compute Routes method,
along with the data it returns.

<br />

| Data resources | Data returned | Return format |
|---|---|---|
| [ComputeRoutes](https://developers.google.com/maps/documentation/routes/compute_route_directions) | Returns routes, legs, and steps for a route, with alternate routes, if requested. | JSON |

<br />

### How to use Compute Routes

|---|---|---|
| 1 | **Get set up** | Start with [Set up your Google Cloud project](https://developers.google.com/maps/documentation/routes/cloud-setup) and complete the setup instructions that follow. |
| 2 | **Understand how the Routes API bills** | For information, see [Usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing). |
| 3 | **Compute a route and review the response** | For more information, see [Get a route](https://developers.google.com/maps/documentation/routes/compute_route_directions) and [Review the route responses](https://developers.google.com/maps/documentation/routes/understand-route-response). |

### Available client libraries

For a list of the available client libraries for
Compute Routes, see
[Client libraries](https://developers.google.com/maps/documentation/routes/client-libraries).

## What's next

- [Get a route](https://developers.google.com/maps/documentation/routes/compute_route_directions)
- [Available route options](https://developers.google.com/maps/documentation/routes/route-opt)
- [Choose what information to return](https://developers.google.com/maps/documentation/routes/choose_fields)
- [Migrate from Directions API (Legacy)](https://developers.google.com/maps/documentation/routes/migrate-routes)
- [Migrate from the Routes API preview to GA](https://developers.google.com/maps/documentation/routes/migrate-routes-preview)

    # Specify locations for a route

**European Economic Area (EEA) developers**

> [!NOTE]
> If your billing address is in the European Economic Area, effective on 8 July 2025, the [Google Maps Platform EEA Terms of Service](https://cloud.google.com/terms/maps-platform/eea) will apply to your use of the Services. Functionality varies by region. [Learn more](https://developers.google.com/maps/comms/eea/faq).

To calculate a route, you must specify at a minimum the locations of the route
origin and route destination. You define these locations as *waypoints* on the
route.

In addition to origin and destination, you can specify different types of
waypoints and how to handle waypoints for a route. For more information and
examples, see these topics:

- [Specify vehicle heading and side of road](https://developers.google.com/maps/documentation/routes/location_modifiers)
- [Specify intermediate waypoints](https://developers.google.com/maps/documentation/routes/intermed_waypoints)
- [Set a stop along a route](https://developers.google.com/maps/documentation/routes/stop_over)
- [Set a point for a route to pass through](https://developers.google.com/maps/documentation/routes/pass-through)
- [Optimize the order of stops on your route](https://developers.google.com/maps/documentation/routes/opt-way)

## Specify locations for a route

You represent a location by creating a [Waypoint (REST)](https://developers.google.com/maps/documentation/routes/reference/rest/v2/Waypoint)
or [Waypoint (gRPC)](https://developers.google.com/maps/documentation/routes/reference/rpc/google.maps.routing.v2#waypoint) object. In the
waypoint definition, you can specify a location in any of the following ways:

- [Place ID](https://developers.google.com/maps/documentation/routes/specify_location#place_id) (preferred)
- [Latitude/longitude coordinates](https://developers.google.com/maps/documentation/routes/specify_location#lat_long)
- [Address string](https://developers.google.com/maps/documentation/routes/specify_location#text_string) ("Chicago, IL" or "Darwin, NT, Australia")
- [Navigation point token](https://developers.google.com/maps/documentation/routes/specify_location#navigation_point_token)
- [Plus Code](https://developers.google.com/maps/documentation/routes/specify_location#plus_code)

You can specify locations for all waypoints in a request the same way,
or you can mix them. For example, you can use latitude/longitude coordinates for
the origin waypoint and use a place ID for the destination waypoint.

For efficiency and accuracy, use place IDs instead of latitude/longitude
coordinates or address strings. Place IDs are uniquely explicit and provide
geocoding benefits for routing such as access points and traffic variables. They
help avoid the following situations that can result from other ways of
specifying a location:

- Using latitude/longitude coordinates can result in the location being snapped to the road nearest to those coordinates - which might not be an access point to the property, or even a road that quickly or safely leads to the destination.
- Address strings must first be geocoded by the Routes API to convert them to latitude/longitude coordinates before it can calculate a route. This conversion can affect performance.

### Specify a location as a place ID

You can use a place ID to specify the location of a waypoint. Because
latitude and longitude coordinates are snapped to roads, you might find a
place ID offers better results in some circumstances.

Retrieve place IDs from the [Geocoding API](https://developers.google.com/maps/documentation/geocoding) and
the [Places API](https://developers.google.com/maps/documentation/places/web-) (including Place
Autocomplete). For more about place IDs, see the
[Place ID overview](https://developers.google.com/maps/documentation/places/web-service/place-id).

The following example uses the `placeId` property to pass a place ID for both
the `origin` and `destination`:

```json
{
  "origin":{
    "placeId": "ChIJayOTViHY5okRRoq2kGnGg8o"
  },
  "destination":{
    "placeId": "ChIJTYKK2G3X5okRgP7BZvPQ2FU"
  },
  ...
}
```

### Specify a location as latitude and longitude coordinates

To define location in a waypoint, specify the
[Location (REST)](https://developers.google.com/maps/documentation/routes/reference/rest/v2/Location) or
[Location(gRPC)](https://developers.google.com/maps/documentation/routes/reference/rpc/google.maps.routing.v2#location) by using
latitude/longitude coordinates.

For example, specify a waypoint for the route `origin` and `destination`
using `latitude` and `longitude` coordinates:

```json
{
  "origin":{
    "location":{
      "latLng":{
        "latitude": 37.419734,
        "longitude": -122.0827784
      }
    }
  },
  "destination":{
    "location":{
      "latLng":{
        "latitude": 37.417670,
        "longitude": -122.079595
      }
    }
  },
...
}
```

> [!NOTE]
> **Note:** The points specified by latitude/longitude coordinates are snapped to roads and might not provide the accuracy your app needs. Use latitude/longitude coordinates when you are confident the values truly specify the points your app needs for routing without regard to possible access points or additional geocoding details.

### Specify a location as an address string

Address strings are literal addresses represented by a string (such as "1600
Amphitheatre Parkway, Mountain View, CA"). Geocoding is the process of
converting an address string into latitudes and longitude coordinates (such as
latitude 37.423021 and longitude -122.083739).

When you pass an address string as the location of a waypoint, Routes API
internally geocodes the string to convert it to latitude and longitude
coordinates.

> [!NOTE]
> **Note:** The latitude and longitude coordinates might be different from those returned by the [Geocoding API](https://developers.google.com/maps/documentation/geocoding). For example, Routes API might return coordinates for a building entrance rather than for its center.

For example, to calculate a route you specify a waypoint for the route `origin` and
`destination` using address strings:

```json
{
  "origin":{
    "address": "1600 Amphitheatre Parkway, Mountain View, CA"
  },
  "destination":{
    "address": "450 Serra Mall, Stanford, CA 94305, USA"
  },
  ...
}
```

In this example, the Routes API geocodes both addresses to convert them to
latitude and longitude coordinates.

If the address value is ambiguous, the Routes API might invoke a search to
disambiguate from similar addresses. For example, "1st Street" could be a
complete value or a partial value for "1st street NE" or "1st St SE". This
result may be different from that returned by the Geocoding API. You can avoid
possible misinterpretations using place IDs.

#### Set the region for the address

If you pass an incomplete address string as the location of a waypoint, the API
might use the wrong geocoded latitude/longitude coordinates. For example,
you make a request specifying "Toledo" as the origin and "Madrid" as the
destination for a driving route:

```json
{
  "origin":{
    "address": "Toledo"
  },
  "destination":{
    "address": "Madrid"
  },
  "travelMode": "DRIVE"
}
```

In this example, "Toledo" is interpreted as a city in the state of
Ohio in the United States, not in Spain. Therefore, the request returns
an empty array, meaning no routes exists:

```json
{
  []
}
```

You can configure the API to return results biased to a particular region by
including the `regionCode` parameter. This parameter specifies the region code as a
[ccTLD ("top-level domain")](https://en.wikipedia.org/wiki/List_of_Internet_top-level_domains#Country_code_top-level_domains)
two-character value. Most ccTLD codes are identical to ISO 3166-1 codes, with
some notable exceptions. For example, the United Kingdom's ccTLD is "uk"
(.co.uk) while its ISO 3166-1 code is "gb" (technically for the entity of "The
United Kingdom of Great Britain and Northern Ireland").

A directions request for "Toledo" to "Madrid" that includes the `regionCode`
parameter returns appropriate results because "Toledo" is interpreted as a
city in Spain:

```json
{
  "origin":{
    "address": "Toledo"
  },
  "destination":{
    "address": "Madrid"
  },
  "travelMode": "DRIVE",
  "regionCode": "es"
}
```

The response now contains the route calculated from Toledo, Spain to
Madrid, Spain:

```json
{
  "routes": [
    {
      "distanceMeters": 75330,
      "duration": "4137s",
      ...
    }
  ]
}
```

### Specify a location as a navigation point token

> [!WARNING]
> This product or feature is in Preview (pre-GA). Pre-GA products and features might have limited support, and changes to pre-GA products and features might not be compatible with other pre-GA versions. Pre-GA Offerings are covered by the [Google
> Maps Platform Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms). For more information, see the [launch stage
> descriptions](https://developers.google.com/maps/launch-stages).

A navigation point token is a string that encodes a location and additional route context. Navigation point tokens can provide precise routing to specific access points near entrances, loading docks, or designated pick-up areas. This is useful in cases like food delivery or
rideshare, where the pickup or dropoff point may be ambiguous.

You can obtain a navigation point token by calling the Destinations method of the [Geocoding API](https://developers.google.com/maps/documentation/geocoding).


To specify a navigation point token:

1. Obtain a `navigationPointToken` from the `SearchDestinations` method of the [Geocoding API](https://developers.google.com/maps/documentation/geocoding). [See the Geocoding API documentation for more information.](https://developers.google.com/maps/documentation/geocoding/navigation-point-tokens)
2. Create a Waypoint by passing in the `navigationPointToken`.

The following example uses the `navigation_point_token` property to pass a navigation point token for both the `origin` and `destination`:

```json
{
  "origin":{
    "navigation_point_token": "ENCODED_NAVIGATION_POINT_TOKEN_FOR_ORIGIN"
  },
  "destination":{
    "navigation_point_token": "ENCODED_NAVIGATION_POINT_TOKEN_FOR_DESTINATION"
  },
  ...
}
```

### Specify a location as a Plus Code

Many people don't have a precise address, which can make it difficult for them
to receive deliveries. Or, people with an address might prefer to accept
deliveries at more specific locations, such as a back entrance or a loading
dock.

Plus Codes are like street addresses for people or places that don't have an
actual address. Instead of addresses with street names and numbers, Plus Codes
are based on latitude/longitude coordinates, and are displayed as numbers and
letters.

Google developed [Plus Codes](https://maps.google.com/pluscodes/)
to give the benefit of addresses to everyone and everything. A Plus Code is an encoded
location reference, derived from latitude/longitude coordinates, that
represents an area: 1/8000th of a degree by 1/8000th of a degree (about 14m x
14m at the equator) or smaller. You can use Plus Codes as a replacement for
street addresses in places where they don't exist or where buildings are not
numbered or streets are not named.

Plus Codes must be formatted as a global code or a compound code:

- A **global code** is composed of a 4 character **area code** and 6 character or longer **local code** .

  For example, for the address "1600 Amphitheatre Parkway,
  Mountain View, CA", the global code is "849V" and the local code is
  "CWC8+R9". You then use the entire 10 character Plus Code to specify the
  location value as "849VCWC8+R9".
- A **compound code** is composed of a 6 character or longer **local code** combined with an explicit location.

  For example, the address "450 Serra
  Mall, Stanford, CA 94305, USA" has a local code of "CRHJ+C3". For a compound
  address, combine the local code with the city, state, ZIP code, and country
  portion of the address in the form "CRHJ+C3 Stanford, CA 94305, USA".

  For example, calculate a route by specifying a waypoint for the route `origin`
  and `destination` using Plus Codes:

  ```json
  {
    "origin":{
      "address": "849VCWC8+R9"
    },
    "destination":{
      "address": "CRHJ+C3 Stanford, CA 94305, USA"
    },
    "travelMode": "DRIVE"
  }
  ```

Plus Codes are supported in Google Maps Platform APIs including
[Place Autocomplete](https://developers.google.com/maps/documentation/places/web-service/autocomplete),
[Place Details](https://developers.google.com/maps/documentation/places/web-service/details),
[Directions API (Legacy)](https://developers.google.com/maps/documentation/directions), and
[Geocoding API](https://developers.google.com/maps/documentation/geocoding).
For example, you can use Geocoding API to reverse geocoding a
location specified by latitude/longitude coordinates to determine the
location's Plus Code.

# Review the route response

**European Economic Area (EEA) developers**

> [!NOTE]
> If your billing address is in the European Economic Area, effective on 8 July 2025, the [Google Maps Platform EEA Terms of Service](https://cloud.google.com/terms/maps-platform/eea) will apply to your use of the Services. Functionality varies by region. [Learn more](https://developers.google.com/maps/comms/eea/faq).

When the Routes API computes a route, it takes the waypoints and
configuration parameters you provide as input. The API then returns a response
that contains the *default* route and one or more alternative routes.

Your response can include different types of routes and other data, based on the
fields you request:

| To include this in the response | See this documentation |
|---|---|
| The most fuel or energy efficient route based on the vehicle's engine type. | [Configure Eco-friendly routes](https://developers.google.com/maps/documentation/routes/eco-routes) |
| Up to three alternative routes | [Request alternate routes](https://developers.google.com/maps/documentation/routes/alternative-routes) |
| The polyline for an entire route, for each leg of a route, and for each step of a leg. | [Request route polylines](https://developers.google.com/maps/documentation/routes/traffic_on_polylines) |
| The estimated tolls, taking into consideration any toll price discounts or passes available to the driver or vehicle. | [Calculate toll fees](https://developers.google.com/maps/documentation/routes/calculate_toll_fees) |
| Localized responses by language codes and measurement unit (imperial or metric). | [Request localized values](https://developers.google.com/maps/documentation/routes/localized-values) |
| To format the navigation instructions as an HTML text string, add `HTML_FORMATTED_NAVIGATION_INSTRUCTIONS` to `extraComputations`. | [Extra Computations](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#extracomputation) |

For the complete list of input options, see [Available route options](https://developers.google.com/maps/documentation/routes/route-opt)
and the
[Request body](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#request-body).

Using the response, you can provide your customers with the information
necessary to select the appropriate route for their requirements.

> [!NOTE]
> **Note:** To get a better idea of how the API handles different types of route requests, [Try the demo](https://developers.google.com/maps/documentation/routes/demo). The demo lets you enter addresses and then view the response as visualized content.

## About field masks

When you call a method to compute a route, you must specify a field
mask that defines which fields you want returned in the response. There is no
default list of returned fields. If you omit this list, the methods return an
error.

The examples in this document show the entire response object without taking
field masks into consideration. In a production environment, your response would
only include the fields that you explicitly specify in the field mask.

For more information, see [Choose what information to return](https://developers.google.com/maps/documentation/routes/choose_fields).

## About displaying copyrights

You must include the following copyright statement when displaying the results to your users:

`Powered by Google, ©YEAR Google`

For example:

`Powered by Google, ©2023 Google`

## About routes, legs, and steps

Before looking at the response returned by the Routes API, you
should have an understanding of the components that make up a route:

![The route, leg, and step.](https://developers.google.com/static/maps/documentation/routes/images/route-leg-step.png)

Your response may contain information about each of these route components:

- **Route** : The entire trip from the origin waypoint, through any
  intermediate waypoints, to the destination waypoint. A route consists of one
  or more *legs*.

- **Leg** : The path from one waypoint in a route to the next waypoint in the
  route. Each leg consists of one or more discrete *steps*.

  A route contains a separate leg for the path from each waypoint to the next.
  For example, if the route contains a single origin waypoint and a single
  destination waypoint, then the route contains a single leg. For each
  additional waypoint you add to the route after the origin and destination,
  called an *intermediate waypoint*, the API adds a separate leg.

  The API does not add a leg for a *pass-through* intermediate waypoint. For
  example, a route that contains an origin waypoint, a pass-through
  intermediate waypoint, and a destination waypoint contains just one leg from
  the origin to the destination, while passing through the waypoint. For more
  information about pass-through waypoints, see
  [Define a pass-through waypoint](https://developers.google.com/maps/documentation/routes/intermed_waypoints#define_a_pass-through_waypoint).
- **Step**: A single instruction along the leg of a route. A step is the most
  atomic unit of a route. For example, a step can indicate "Turn left on Main
  Street''.

## What's in the response

The [JSON object](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#response-body)
representing the API response contains the following top-level properties:

- `routes`, an array of elements of type
  [Route](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#Route).
  The `routes` array contains one element for each route returned by the API.
  The array can contain a maximum of five elements: the default route, the
  eco-friendly route, and up to three alternative routes.

- `geocodingResults`, an array of elements of type
  [GeocodingResults](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#geocodingresults).
  For every location in the request (origin, destination, or intermediate
  waypoint) that you specified as an **address string** or as a **Plus code** ,
  the API performs a place ID lookup. Each element of this array contains the
  place ID corresponding to a location. Locations in the request specified as
  a **place ID** or as **latitude/longitude coordinates** are not included.
  If you've specified all locations using place IDs or latitude and longitude
  coordinates, this array is not provided.

- `fallbackInfo`, of type
  [FallbackInfo](https://developers.google.com/maps/documentation/routes/reference/rest/v2/FallbackInfo).
  If the API is not able to compute a route from all of the input properties,
  it might fallback to using a different way of computation. When fallback
  mode is used, this field contains detailed info about the fallback
  response. Otherwise this field is unset.

The response has the form:

```json
{
  // The routes array.
  "routes": [
    {
      object (Route)
    }
  ],
  // The place ID lookup results.
  "geocodingResults": [
    {
      object (GeocodedWaypoint)
    }
  ],
  // The fallback property.
  "fallbackInfo": {
    object (FallbackInfo)
  }
}
```

### Decipher the routes array

The response contains the `routes` array, where each array element is of type
[Route](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#Route).
Each array element represents an entire route from origin to destination. The
API always returns at least one route, called the default route.

You can request additional routes. If you request an
[eco-friendly route](https://developers.google.com/maps/documentation/routes/eco-routes), then the array can contain two elements: the
default route and the eco-friendly route. Or, set `computeAlternativeRoutes` to
`true` in the request to add up to three alternative routes to the response.

Each route in the array is identified with the `routeLabels` array property:

| Value | Description |
|---|---|
| `DEFAULT_ROUTE` | Identifies the default route. |
| `FUEL_EFFICIENT` | Identifies the eco-friendly route. |
| `DEFAULT_ROUTE_ALTERNATE` | **I**ndicates an alternative route. |

The `legs` array contains the definition of each leg of the route. The remaining
properties, such as `distanceMeters`, `duration`, and `polyline,` contain
information about the route as a whole:

```json
{
  "routeLabels": [
    enum (RouteLabel)
  ],
  "legs": [
    {
      object (RouteLeg)
    }
  ],
  "distanceMeters": integer,
  "duration": string,
  "routeLabels": [string],
  "staticDuration": string,
  "polyline": {
    object (Polyline)
  },
  "description": string,
  "warnings": [
    string
  ],
  "viewport": {
    object (Viewport)
  },
  "travelAdvisory": {
    object (RouteTravelAdvisory)
  }
  "routeToken": string
}
```

Because of current driving conditions and other factors, the default route and
the eco-friendly route can be the same. In this case, `routeLabels` array
contains both labels: `DEFAULT_ROUTE` and `FUEL_EFFICIENT`.

```json
{
  "routes": [
    {
      "routeLabels": [
        "DEFAULT_ROUTE",
        "FUEL_EFFICIENT"
      ],
     ...
    }
  ]
}
```

### Understand the legs array

Each `route` in the response contains a `legs` array, where each `legs` array
element is of type
[RouteLeg](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#routeleg).
Each leg in the array defines the path from one waypoint to the next waypoint
along the route. A route always contains at least one leg.

The `legs` property contains the definition of each step along the leg in the
`steps` array. The remaining properties, such as `distanceMeters`, `duration`,
and `polyline` contain information about the leg.

```json
{
  "distanceMeters": integer,
  "duration": string,
  "staticDuration": string,
  "polyline": {
    object (Polyline)
  },
  "startLocation": {
    object (Location)
  },
  "endLocation": {
    object (Location)
  },
  "steps": [
    {
      object (RouteLegStep)
    }
  ],
  "travelAdvisory": {
    object (RouteLegTravelAdvisory)
  }
}
```

### Understand the steps array

Each leg in the response contains a `steps` array, where each `steps` array
element is of type
[RouteLegStep](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#routelegstep).
A step corresponds to a single instruction along the leg. A leg always contains
at least one step.

Each element in the `steps` array includes the `navigationInstruction`
property, of type
[NavigationInstruction](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#navigationinstruction),
which contains the step instruction. For example:

```json
"navigationInstruction": {
  "maneuver": "TURN_LEFT",
  "instructions": "Turn left toward Frontage Rd"
}
```

The `instructions` might contain additional information about the step. For
example:

```json
"navigationInstruction": {
  "maneuver": "TURN_SLIGHT_LEFT",
  "instructions": "Slight left (signs for I-90 W/Worcester)nParts of this road may be closed at certain times or days"
}
```

The remaining properties in the step describe information about the step, such
as `distanceMeters`, `duration`, and `polyline`:

```json
{
  "distanceMeters": integer,
  "staticDuration": string,
  "polyline": {
    object (Polyline)
  },
  "startLocation": {
    object (Location)
  },
  "endLocation": {
    object (Location)
  },
  "navigationInstruction": {
    object (NavigationInstruction)
  }
}
```

### Specify the language of the step instructions

The API returns route information in the local language, transliterated to a
script readable by the user, if necessary, while observing the preferred
language. Address components are all returned in the same language.

- Use the `languageCode` parameter of a
  [request](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#request-body) to
  explicitly set the route language from the [list of supported
  languages](https://developers.google.com/maps/faq#languagesupport). Google often updates the supported
  languages, so this list may not be exhaustive.

- If a name is not available in the specified language, the API uses the
  closest match.

- The specified language can influence the set of results that the
  API chooses to return and the order in which they are returned. The
  geocoder interprets abbreviations differently depending on language, such as
  the abbreviations for street types, or synonyms that may be valid in one
  language but not in another. For example, utca and tér are synonyms for
  street in Hungarian.

## Understand the geocodingResults array

For every location in the request (origin, destination, or intermediate
waypoint) that was specified as an **address string** or as a **Plus code** , the
API attempts to find the most relevant location which has a corresponding place
ID. Each element of the
[`geocodingResults`](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#geocodingresults)
array contains the `placeID` field
containing the location as a place ID and a `type` field specifying the location
type, such as `street_address`, `premise`, or `airport`.

> [!NOTE]
> **Note:** The API does not include locations in the request specified as a place ID or as latitude and longitude coordinates. If they are all in these formats, this array is not provided.

The `geocodingResults` array contains three fields:

- `origin`: If it was specified as an address string or as a Plus code, the
  place ID of the origin. Otherwise, this field is omitted from the response.

- `destination`: If it was specified as an address string or as a Plus code,
  the place ID of the destination. Otherwise, this field is omitted from the
  response.

- `intermediates`: An array containing the place ID of any intermediate
  waypoints specified as an address string or as a Plus code. If you specify
  an intermediate waypoint using a place ID or latitude and
  longitude coordinates, it is omitted from the response. Use the
  `intermediateWaypointRequestIndex` property in the response to determine
  which intermediate waypoint in the request corresponds to the place ID in
  the response.

> [!NOTE]
> **Note:** If a requested location does not exist or cannot be found, the API still populates the `geocodingResults` array in the response. However, the `routes` array is empty because no route can be computed for a location that cannot be found.

```json
"geocodingResults": {
    "origin": {
        "geocoderStatus": {},
        "type": [
             enum (Type)
        ],
        "placeId": string
    },
    "destination": {
        "geocoderStatus": {},
        "type": [
            enum (Type)
        ],
        "placeId": string
    },
    "intermediates": [
        {
            "geocoderStatus": {},
            "intermediateWaypointRequestIndex": integer,
            "type": [
                enum (Type)
            ],
            "placeId": string
        },
        {
           "geocoderStatus": {},
           "intermediateWaypointRequestIndex": integer,
            "type": [
                enum (Type)
            ],
            "placeId": string
        }
    ]
}
```

## Understand localized response values

Localized response values are an additional response field that provides
localized text for returned parameter values. Localized text is provided for
trip duration, distance, and unit system (metric or imperial). You request
localized values using a field mask, and can either specify the language and
unit system or use the values inferred by the API. For details, see
[LocalizedValues](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#routelegsteplocalizedvalues).

For example, if you specify a language code for German (de) and imperial
units, you get a value for `distanceMeters` of 49889.7,
but also localized text providing that distance measurement in German and
imperial units, so "31 Meile."

Here is an example of what you would see for localized values:

```restructuredtext
{ "localized_values":
  {
    "distance": { "text": "31,0 Meile/n" },
    "duration": { "text": 38 Minuten}.
    "static_duration": { "text": 36 Minuten}.
  }
}
```

> [!NOTE]
> Note: You get two values for the expected duration: `duration` uses the traffic model you specify, and `static_duration` does not take traffic into account. So, if your requested traffic model is `TRAFFIC_UNAWARE` these times are identical.

If you don't specify the language or unit system, the API infers the language
and units as follows:

- The `ComputeRoutes` method infers the location and distance units from the origin waypoint. So for a routing request in the US, the API infers `en-US` language and `IMPERIAL` units.
- The `ComputeRouteMatrix` method defaults to 'en-US' language and METRIC units.

    # Handle request errors

**European Economic Area (EEA) developers**

> [!NOTE]
> If your billing address is in the European Economic Area, effective on 8 July 2025, the [Google Maps Platform EEA Terms of Service](https://cloud.google.com/terms/maps-platform/eea) will apply to your use of the Services. Functionality varies by region. [Learn more](https://developers.google.com/maps/comms/eea/faq).

The Routes API returns error messages as part of the
response to a method call. For example, if you omit the API key from the
request, the method returns:

```json
{
  "error": {
    "code": 403,
    "message": "The request is missing a valid API key.",
    "status": "PERMISSION_DENIED"
  }
}
```

If you omit a required body parameter, such as `origin`, the method
returns:

```json
{
  "error": {
    "code": 400,
    "message": "Origin and destination must be set.",
    "status": "INVALID_ARGUMENT"
  }
}
```

For more information on errors and error handling, see
[Errors](https://cloud.google.com/apis/design/errors).
