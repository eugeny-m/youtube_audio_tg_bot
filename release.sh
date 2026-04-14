#!/bin/bash
set -e

IMAGE_NAME="youtube_tg"
REMOTE_HOST="ss_admin_timeweb"
REMOTE_DIR="/opt/youtube_tg_bot"
MAIN_BRANCH="main"
DEV_BRANCH="develop"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

cleanup() {
    local current
    current=$(git branch --show-current)
    if [ "$current" != "$DEV_BRANCH" ]; then
        echo -e "${YELLOW}Returning to $DEV_BRANCH...${NC}"
        git checkout "$DEV_BRANCH"
    fi
}
trap cleanup EXIT

# 1. Check clean working tree
if [ -n "$(git status --porcelain | grep -v '^??')" ]; then
    echo -e "${RED}Error: working tree is not clean. Commit or stash changes first.${NC}"
    exit 1
fi

# 2. Get current version from latest tag
LATEST_TAG=$(git tag --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
if [ -z "$LATEST_TAG" ]; then
    LATEST_TAG="v0.0.0"
    echo -e "${YELLOW}No existing tags found, starting from v0.0.0${NC}"
else
    echo -e "${GREEN}Current version: ${LATEST_TAG}${NC}"
fi

# Parse version
MAJOR=$(echo "$LATEST_TAG" | sed 's/^v//' | cut -d. -f1)
MINOR=$(echo "$LATEST_TAG" | sed 's/^v//' | cut -d. -f2)
PATCH=$(echo "$LATEST_TAG" | sed 's/^v//' | cut -d. -f3)

# 3. Interactive bump selection
echo ""
echo "What to bump?"
echo "  1) patch  → v${MAJOR}.${MINOR}.$((PATCH + 1))"
echo "  2) minor  → v${MAJOR}.$((MINOR + 1)).0"
echo "  3) major  → v$((MAJOR + 1)).0.0"
echo ""
read -rp "Choose [1/2/3]: " CHOICE

case $CHOICE in
    1) PATCH=$((PATCH + 1)) ;;
    2) MINOR=$((MINOR + 1)); PATCH=0 ;;
    3) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
    *) echo -e "${RED}Invalid choice${NC}"; exit 1 ;;
esac

NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH}"
echo -e "${GREEN}New version: ${NEW_VERSION}${NC}"

# 4. Confirm
read -rp "Proceed with release ${NEW_VERSION}? [y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# 5. Merge develop → master
echo -e "${YELLOW}Merging ${DEV_BRANCH} → ${MAIN_BRANCH}...${NC}"
git checkout "$MAIN_BRANCH"
git merge "$DEV_BRANCH" -m "release: merge ${DEV_BRANCH} for ${NEW_VERSION}"

# 6. Tag
echo -e "${YELLOW}Creating tag ${NEW_VERSION}...${NC}"
git tag "$NEW_VERSION"

# 7. Push
echo -e "${YELLOW}Pushing ${MAIN_BRANCH} and tags...${NC}"
git push origin "$MAIN_BRANCH" --tags

# 8. Build image
echo -e "${YELLOW}Building Docker image ${IMAGE_NAME}:${NEW_VERSION} (linux/amd64)...${NC}"
docker buildx build --network host --platform=linux/amd64 -t "${IMAGE_NAME}:${NEW_VERSION}" -f prod.Dockerfile .

# 9. Save image
ARCHIVE="${IMAGE_NAME}_${NEW_VERSION}.tar.gz"
echo -e "${YELLOW}Saving image to ${ARCHIVE}...${NC}"
docker save "${IMAGE_NAME}:${NEW_VERSION}" | gzip > "$ARCHIVE"

# 10. SCP to server
echo -e "${YELLOW}Uploading ${ARCHIVE} to ${REMOTE_HOST}:${REMOTE_DIR}/...${NC}"
scp "$ARCHIVE" "${REMOTE_HOST}:${REMOTE_DIR}/"

# 11. Load image on server and cleanup
echo -e "${YELLOW}Loading image on server...${NC}"
ssh "$REMOTE_HOST" "docker load -i ${REMOTE_DIR}/${ARCHIVE} && rm -f ${REMOTE_DIR}/${ARCHIVE}"

# 12. Cleanup local archive
rm -f "$ARCHIVE"

echo ""
echo -e "${GREEN}Release ${NEW_VERSION} complete!${NC}"
echo -e "${GREEN}Image ${IMAGE_NAME}:${NEW_VERSION} is loaded on ${REMOTE_HOST}${NC}"
