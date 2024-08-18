#!/bin/bash

docker compose down

docker rmi uglyfeed-uglyfeed

docker compose up -d
