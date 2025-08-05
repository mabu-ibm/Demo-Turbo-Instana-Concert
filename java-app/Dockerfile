FROM maven:3.8.4-openjdk-11-slim AS build
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn clean package -DskipTests

FROM openjdk:11-jre-slim
LABEL vulnerability="CVE-2021-44228"
LABEL log4j-version="2.14.1"

RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /app/target/vulnerable-echo-service-*.jar app.jar
RUN chown -R appuser:appuser /app

USER appuser

ENV JAVA_OPTS="-Xmx512m -Xms256m"
ENV SERVER_PORT=8085
ENV LOG4J2_DISABLE_JNDI=false

EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8085/health || exit 1

CMD java $JAVA_OPTS -Dserver.port=$SERVER_PORT -jar app.jar
