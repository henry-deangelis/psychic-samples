
# hadolint ignore=DL3007
FROM python:3.12.3
ENV PYTHONUNBUFFERED=1

# Change this file as much as needed to fit with your implementation
#
# Just make sure that it fits with the running instructions from the README

WORKDIR /app
COPY thelogparser.py .
RUN pip3 install pathvalidate
RUN pip3 install statsd

ENTRYPOINT [ "python3", "commonlogparser.py"]
CMD ["--in", "infile", "--out", "outfilejson", "--max-client-ips", "10", "--max-paths", "10" ]