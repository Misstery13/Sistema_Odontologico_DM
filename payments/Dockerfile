FROM golang:1.23-alpine AS build
WORKDIR /src
COPY . .
# ponytail: go.sum se genera en el build; versionarlo cuando haya Go instalado en local
RUN go mod tidy && CGO_ENABLED=0 go build -o /payments .

FROM alpine:3.20
COPY --from=build /payments /payments
USER nobody
EXPOSE 8080
CMD ["/payments"]
