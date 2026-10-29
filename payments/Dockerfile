FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /payments .

FROM alpine:3.22
COPY --from=build /payments /payments
USER nobody
EXPOSE 8080
CMD ["/payments"]
