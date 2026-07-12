# US Pet Groomer Scraper

Scrape pet grooming business data for any US state — names, addresses, phones, hours, and service offerings. Perfect for lead generation, market research, and competitive intelligence in the $10B+ US pet grooming industry.

## How it works

1. **Discovery phase** — Searches DuckDuckGo for pet groomers in each city (3 queries: "pet groomer", "dog grooming", "pet grooming salon")
2. **Crawl phase** — Visits each groomer's website with Playwright (headless Chromium)
3. **Extraction** — Parses name, address, phone, hours, services using BeautifulSoup + regex
4. **Output** — Clean JSON dataset, exportable as CSV/Excel

No API keys. No login. Just pick a state and run.

## Output fields

| Field | Type | Description |
|---|---|---|
| name | string | Business name |
| url | string | Website URL |
| city | string | City |
| state | string | State |
| address | string | Street address (best-effort) |
| phone | string | Phone number |
| mobile_grooming | boolean | Offers mobile/house-call grooming |
| self_wash | boolean | Has self-serve dog wash stations |
| dog_grooming | boolean | Grooms dogs |
| cat_grooming | boolean | Grooms cats |
| nail_trim | boolean | Nail trimming service |
| bathing | boolean | Bathing/shampoo service |
| haircut_styling | boolean | Haircut/breed-specific styling |
| teeth_cleaning | boolean | Teeth cleaning/dental |
| sat_hours | string | Saturday hours (if found) |
| sun_hours | string | Sunday hours (if found) |
| founded | string | Year established (if found) |
| services | string | Specialty services detected |

## Example output

```json
{
  "name": "Paws & Claws Grooming Salon",
  "url": "https://pawsandclawsgrooming.com",
  "city": "Blue Springs",
  "state": "Missouri",
  "address": "123 Main St, Blue Springs, MO 64014",
  "phone": "(816) 555-0123",
  "mobile_grooming": false,
  "self_wash": true,
  "dog_grooming": true,
  "cat_grooming": false,
  "nail_trim": true,
  "bathing": true,
  "haircut_styling": true,
  "teeth_cleaning": false,
  "sat_hours": "Sat 9am-3pm",
  "sun_hours": "",
  "founded": "2015",
  "services": "de-shedding, puppy package, breed-specific cuts"
}
```

## Input parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| state | select | Missouri | US state to scrape |
| maxCities | integer | 0 (all) | Limit cities for testing |
| cityOffset | integer | 0 | Skip N cities before starting — paginate large states across multiple runs |
| maxGroomersPerCity | integer | 5 | Max websites crawled per city |

## Runtime estimates

| State size | Cities | Est. time |
|---|---|---|
| Small (WY, VT) | ~20-40 | 5-10 min |
| Medium (MO, KS) | ~70-150 | 20-40 min |
| Large (TX, CA) | ~450-600 | 1.5-2 hrs |

Default timeout is 6 hours — enough for any state. For full USA coverage (~10,000 cities), run 50 states as separate tasks.

## Use cases

- **Lead generation** — Build prospect lists for pet product suppliers, mobile groomer apps, pet insurance companies
- **Market research** — Analyze service gaps by geography (where are mobile groomers underserved?)
- **Competitive intelligence** — Map competitors in your area, see what services they offer
- **Franchise scouting** — Find cities with few groomers but large pet-owning populations

## Pricing

**$5 per 1,000 groomers scraped** (Pay per event). Platform usage (compute + proxy) is paid by the user.

| Cost example | |
|---|---|
| Small state (~40 cities) | ~$1.00 |
| Medium state (~200 cities) | ~$5.00 |
| Large state (~600 cities) | ~$15.00 |
| Full USA (~10,000 cities) | ~$250.00 |

## Why no competition?

There are zero dedicated US pet groomer scrapers on the Apify Store. The vet scraper market is also underserved (only 2 actors), and pet grooming is an even larger, more fragmented market with no data provider. You're first to market.

## Limitations

- Address extraction is best-effort — many groomer sites use images or embedded maps
- DuckDuckGo rate limits require ~1 second between cities
- Small towns (<2,000 pop) may genuinely have zero pet groomers
- Mobile-only groomers without websites won't appear in results
