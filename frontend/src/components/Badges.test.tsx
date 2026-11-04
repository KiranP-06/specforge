import { render, screen } from "@testing-library/react";
import { Bar, QualityBadge, StatusBadge } from "./Badges";

describe("badges", () => {
  it("colours the quality score by band", () => {
    render(<><QualityBadge score={92.4} /><QualityBadge score={70} /><QualityBadge score={40} /><QualityBadge score={null} /></>);
    expect(screen.getByText("BQS 92.4").className).toContain("ok");
    expect(screen.getByText("BQS 70.0").className).toContain("warn");
    expect(screen.getByText("BQS 40.0").className).toContain("err");
    expect(screen.getByText("no score")).toBeTruthy();
  });

  it("humanises statuses", () => {
    render(<StatusBadge status="in_progress" />);
    expect(screen.getByText("in progress")).toBeTruthy();
  });

  it("clamps progress bars", () => {
    const { container } = render(<Bar value={140} />);
    expect((container.querySelector(".bar > span") as HTMLElement).style.width).toBe("100%");
  });
});
