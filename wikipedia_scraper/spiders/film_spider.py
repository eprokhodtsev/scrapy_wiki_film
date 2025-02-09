import scrapy
import csv
import os
import json
from wikipedia_scraper.items import WikipediaScraperItem

class FilmsSpider(scrapy.Spider):
    name = "films"
    allowed_domains = ["wikipedia.org", "www.rottentomatoes.com"]
    start_urls = [
        "https://ru.wikipedia.org/wiki/Категория:Фильмы_по_алфавиту",
        "https://ru.wikipedia.org/wiki/Категория:Фильмы_по_годам"
    ]
    visited_file = "visited_films.csv"

    def __init__(self, single_url=None, *args, **kwargs):
        super(FilmsSpider, self).__init__(*args, **kwargs)

        # Initialize visited_films to avoid reprocessing
        self.visited_films = set()
        if os.path.exists(self.visited_file):
            with open(self.visited_file, newline='', encoding='utf-8') as file:
                reader = csv.reader(file)
                self.visited_films = {row[0] for row in reader}

        # Override start_urls if a single URL is provided
        if single_url:
            self.start_urls = [single_url]

    def start_requests(self):
        """Ensures correct request handling, including single_url case."""
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        """Extract film links from the category pages and follow them."""
        film_links = response.css('.mw-category-group a::attr(href)').getall()
        for link in film_links:
            full_link = response.urljoin(link)
            if full_link not in self.visited_films:
                yield response.follow(url=link, callback=self.parse_film)

        # Follow pagination for more movies
        next_page = response.css('a[title="Категория:Фильмы по алфавиту"]::attr(href)').get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

    def parse_film(self, response):
        """Parse film details from Wikipedia pages."""

        def extract_field(field_name, use_link_text=False):
            """Extract and clean table fields from Wikipedia pages."""
            if use_link_text:
                raw_data = response.xpath(f'//tr[th/a[contains(text(), "{field_name}")]]/td//text()').getall()
            else:
                raw_data = response.xpath(f'//tr[th[contains(text(), "{field_name}")]]/td//text()').getall()

            # Clean up extracted text
            cleaned_data = [d.strip() for d in raw_data if d.strip()]
            return ", ".join(cleaned_data).replace(" ,", ",") if cleaned_data else None

        # Extract metadata
        title = response.xpath('//title/text()').get()
        if title:
            title = title.split("—")[0].strip()
            if "Википедия" in title:
                title = title.replace("Википедия", "").strip()

        genre = extract_field("Жанры", use_link_text=True) or extract_field("Жанр")
        director = extract_field("Режиссёр")
        country = extract_field("Страна")
        year = extract_field("Год")

        # Log missing fields for debugging
        if not title:
            self.logger.warning(f"⚠️ Title not found for {response.url}")
            return
        if not genre:
            self.logger.warning(f"⚠️ Genre not found for {title}")
        if not director:
            self.logger.warning(f"⚠️ Director not found for {title}")
        if not country:
            self.logger.warning(f"⚠️ Country not found for {title}")
        if not year:
            self.logger.warning(f"⚠️ Year not found for {title}")

        item = WikipediaScraperItem(
            title=title,
            genre=genre,
            director=director,
            country=country,
            year=year,
            rotten_tomatoes_rating=None  # Placeholder until Rotten Tomatoes lookup
        )

        # Save visited URLs
        try:
            with open(self.visited_file, "a", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow([response.url])
        except Exception as e:
            self.logger.error(f"⚠️ Error writing to {self.visited_file}: {e}")

        # Rotten Tomatoes lookup
        if title:
            search_query = title.replace(" ", "_").lower()
            if search_query:
                rt_url = f"https://www.rottentomatoes.com/m/{search_query}"
                yield scrapy.Request(rt_url, callback=self.parse_rotten_tomatoes, meta={"item": item})
            else:
                self.logger.warning(f"⚠️ Skipping Rotten Tomatoes search for {response.url} (invalid title).")

        yield item  # Ensure data gets stored

    def parse_rotten_tomatoes(self, response):
        """Extract Rotten Tomatoes rating from the movie page."""
        item = response.meta["item"]

        # Check if Rotten Tomatoes returned a 404
        if response.status == 404:
            self.logger.warning(f"⚠️ Rotten Tomatoes page not found for {item['title']}")
            item["rotten_tomatoes_rating"] = "N/A"
            yield item
            return

        # Extract rating using JSON method
        json_data = response.xpath('//script[contains(text(), "scoreBoard")]/text()').get()
        if json_data:
            try:
                json_parsed = json.loads(json_data)
                score = json_parsed.get("scoreBoard", {}).get("tomatometerScore", None)
                item["rotten_tomatoes_rating"] = f"{score}%" if score else "N/A"
            except json.JSONDecodeError:
                self.logger.warning(f"⚠️ Error parsing Rotten Tomatoes JSON for {item['title']}")
                item["rotten_tomatoes_rating"] = "N/A"
        else:
            # Fallback method using CSS selector
            score = response.css('score-board::attr(tomatometer-score)').get()
            item["rotten_tomatoes_rating"] = f"{score}%" if score else "N/A"

        yield item
