import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { previewParts } from "../../lib/geometry";
import type { DesignReport, RocketDesign } from "../../lib/types";
import { createWebGL2Canvas } from "../../lib/webgl";
const colors = { body: "#bcbcbc", fin: "#888888", internal: "#dddddd" };
function disposeGroup(group: THREE.Group) {
  group.traverse((object) => {
    if (object instanceof THREE.Mesh) {
      object.geometry.dispose();
      const materials = Array.isArray(object.material)
        ? object.material
        : [object.material];
      materials.forEach((material) => {
        material.dispose();
      });
    }
  });
  group.clear();
}
export function Rocket3D({
  design,
  report,
  interior,
  selection,
  select,
  fallback,
}: {
  design: RocketDesign;
  report: DesignReport;
  interior: boolean;
  selection: string;
  select: (id: string) => void;
  fallback: (message: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const engine = useRef<{
    scene: THREE.Scene;
    group: THREE.Group;
    camera: THREE.PerspectiveCamera;
    render: () => void;
  } | null>(null);
  const callbacks = useRef({ select, fallback });
  callbacks.current = { select, fallback };
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    let renderer: THREE.WebGLRenderer;
    let context: WebGL2RenderingContext | undefined;
    try {
      const gpu = createWebGL2Canvas();
      context = gpu.context;
      renderer = new THREE.WebGLRenderer({
        canvas: gpu.canvas,
        context,
        alpha: true,
      });
    } catch (error) {
      context?.getExtension("WEBGL_lose_context")?.loseContext();
      callbacks.current.fallback(String(error));
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    element.append(renderer.domElement);
    const scene = new THREE.Scene();
    const group = new THREE.Group();
    scene.add(group);
    const camera = new THREE.PerspectiveCamera(35, 1, 0.001, 1000);
    camera.position.set(1.1, 0.7, 1.4);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.4, 0);
    const render = () => {
      if (element.clientWidth && element.clientHeight) {
        renderer.render(scene, camera);
        renderer.domElement.dataset.rendered = "true";
      }
    };
    controls.addEventListener("change", render);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x777777, 2.5));
    const light = new THREE.DirectionalLight(0xffffff, 2);
    light.position.set(2, 3, 4);
    scene.add(light);
    const resize = new ResizeObserver(() => {
      const width = element.clientWidth,
        height = element.clientHeight;
      if (!width || !height) return;
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      render();
    });
    resize.observe(element);
    let down = [0, 0];
    const pointerDown = (event: PointerEvent) => {
      down = [event.clientX, event.clientY];
    };
    const pointerUp = (event: PointerEvent) => {
      if (Math.hypot(event.clientX - down[0], event.clientY - down[1]) > 4)
        return;
      const rect = element.getBoundingClientRect();
      const ray = new THREE.Raycaster();
      ray.setFromCamera(
        new THREE.Vector2(
          ((event.clientX - rect.left) / rect.width) * 2 - 1,
          (-(event.clientY - rect.top) / rect.height) * 2 + 1,
        ),
        camera,
      );
      const hit = ray
        .intersectObjects(group.children, true)
        .find((item) => typeof item.object.userData.componentId === "string");
      if (hit) callbacks.current.select(hit.object.userData.componentId);
    };
    const lost = (event: Event) => {
      event.preventDefault();
      callbacks.current.fallback("WebGL 컨텍스트를 잃어 2D로 전환했습니다.");
    };
    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointerup", pointerUp);
    renderer.domElement.addEventListener("webglcontextlost", lost);
    controls.update();
    engine.current = { scene, group, camera, render };
    return () => {
      resize.disconnect();
      controls.dispose();
      disposeGroup(group);
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
      engine.current = null;
    };
  }, []);
  useEffect(() => {
    const current = engine.current;
    if (!current) return;
    disposeGroup(current.group);
    const parts = previewParts(design, report);
    for (const part of parts) {
      if (part.type === "internal" && !interior) continue;
      const material = new THREE.MeshStandardMaterial({
        color: part.id === selection ? "#666666" : colors[part.type],
        roughness: 0.8,
        metalness: 0.05,
        transparent: interior && part.type === "body",
        opacity: interior && part.type === "body" ? 0.28 : 1,
        side: THREE.DoubleSide,
        depthWrite: !(interior && part.type === "body"),
      });
      if (part.type === "fin") {
        const outline = report.components.find(
          (p) => p.id === part.id,
        )?.fin_outline_m;
        if (!outline) continue;
        const shape = new THREE.Shape(
          outline.map(([r, z]) => new THREE.Vector2(r, z)),
        );
        for (let i = 0; i < part.count; i++) {
          const geometry = new THREE.ExtrudeGeometry(shape, {
            depth: part.thickness,
            bevelEnabled: false,
          });
          geometry.translate(0, 0, -part.thickness / 2);
          geometry.rotateX((part.cant * Math.PI) / 180);
          geometry.translate(part.radius, part.station, 0);
          geometry.rotateY((i * 2 * Math.PI) / part.count);
          const mesh = new THREE.Mesh(geometry, material.clone());
          mesh.userData.componentId = part.id;
          current.group.add(mesh);
        }
        material.dispose();
      } else if (part.profile.length > 1) {
        const geometry = new THREE.LatheGeometry(
          part.profile.map(([z, r]) => new THREE.Vector2(Math.max(0, r), z)),
          48,
        );
        const mesh = new THREE.Mesh(geometry, material);
        mesh.userData.componentId = part.id;
        current.group.add(mesh);
      } else {
        material.dispose();
      }
    }
    if (interior && design.motor && "chamber_radius" in design.motor) {
      const motor = design.motor;
      const direction =
        motor.coordinate_system_orientation === "combustion_chamber_to_nozzle"
          ? -1
          : 1;
      const mesh = new THREE.Mesh(
        new THREE.CylinderGeometry(
          motor.chamber_radius,
          motor.chamber_radius,
          motor.chamber_height,
          24,
        ),
        new THREE.MeshStandardMaterial({ color: "#999999", roughness: 0.8 }),
      );
      mesh.position.y =
        (design.motor_position || 0) + direction * motor.chamber_position;
      mesh.userData.componentId = "motor";
      current.group.add(mesh);
    }
    const cg = new THREE.Mesh(
      new THREE.SphereGeometry(0.008, 12, 8),
      new THREE.MeshBasicMaterial({ color: "#666666" }),
    );
    cg.position.y = report.effective.center_of_mass_m;
    current.group.add(cg);
    current.render();
  }, [design, report, selection, interior]);
  return (
    <div
      className="canvas-host"
      ref={container}
      role="img"
      aria-label="로켓 3D 형상"
    />
  );
}
