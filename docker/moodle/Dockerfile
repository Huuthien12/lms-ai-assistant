FROM ghcr.io/moodlehq/moodle-php-apache:8.3-bullseye

ARG MOODLE_BRANCH=MOODLE_405_STABLE

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /var/www/html/* \
    && git clone --depth 1 --branch "${MOODLE_BRANCH}" https://github.com/moodle/moodle.git /var/www/html \
    && mkdir -p /var/www/moodledata \
    && chown -R www-data:www-data /var/www/html /var/www/moodledata
